# -*- coding: utf-8 -*-

import base64
import io
import re
from datetime import timedelta
from html import escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class MeetingMinutes(models.Model):
    _name = "np.meeting.minutes"
    _description = "Notulen Meeting"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "meeting_date desc, start_time desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="No. Notulen",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    title = fields.Char(string="Judul Rapat", required=True, tracking=True)
    agenda = fields.Char(string="Agenda", tracking=True)
    meeting_date = fields.Date(
        string="Tanggal",
        required=True,
        default=lambda self: fields.Date.context_today(self),
        tracking=True,
    )
    day_name = fields.Char(
        string="Hari",
        compute="_compute_day_name",
        store=True,
    )
    start_time = fields.Float(string="Mulai", tracking=True)
    end_time = fields.Float(string="Selesai", tracking=True)
    location = fields.Char(string="Tempat", tracking=True)
    department_id = fields.Many2one(
        "hr.department",
        string="Divisi",
        default=lambda self: self._default_department_id(),
        tracking=True,
    )
    note_taker_id = fields.Many2one(
        "hr.employee",
        string="Notulis",
        default=lambda self: self._default_employee_id(),
        tracking=True,
    )
    participant_ids = fields.Many2many(
        "hr.employee",
        "np_meeting_minutes_hr_employee_rel",
        "meeting_id",
        "employee_id",
        string="Peserta Rapat",
        tracking=True,
    )
    participant_names = fields.Text(
        string="Peserta",
        compute="_compute_participant_names",
    )
    line_ids = fields.One2many(
        "np.meeting.minutes.line",
        "meeting_id",
        string="Pembahasan",
        copy=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        readonly=True,
    )
    requested_by = fields.Many2one(
        "res.users",
        string="Dibuat Oleh",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    export_file = fields.Binary(string="Export File", attachment=True)
    export_filename = fields.Char(string="Export Filename")
    approver_id = fields.Many2one(
        "res.users",
        string="Approver",
        tracking=True,
    )
    approved_by = fields.Many2one(
        "res.users",
        string="Disetujui Oleh",
        readonly=True,
    )
    approved_date = fields.Datetime(string="Tanggal Approval", readonly=True)
    rejected_by = fields.Many2one(
        "res.users",
        string="Ditolak Oleh",
        readonly=True,
    )
    rejected_date = fields.Datetime(string="Tanggal Penolakan", readonly=True)
    approval_note = fields.Text(string="Catatan Approval", tracking=True)
    carry_forward_source_id = fields.Many2one(
        "np.meeting.minutes",
        string="Sumber Carry Forward",
        domain="[('id', '!=', id)]",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("waiting_approval", "Menunggu Approval"),
            ("approved", "Disetujui"),
            ("rejected", "Ditolak"),
            ("done", "Selesai"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )
    line_count = fields.Integer(compute="_compute_counts")
    change_count = fields.Integer(compute="_compute_counts")
    carry_forward_count = fields.Integer(compute="_compute_counts")
    is_admin = fields.Boolean(compute="_compute_permissions")
    can_edit_meeting = fields.Boolean(compute="_compute_permissions")
    can_submit_approval = fields.Boolean(compute="_compute_permissions")
    can_approve = fields.Boolean(compute="_compute_permissions")
    can_reset = fields.Boolean(compute="_compute_permissions")
    can_carry_forward = fields.Boolean(compute="_compute_permissions")

    @api.model
    def _default_employee_id(self):
        employee = self.env["hr.employee"].sudo().search(
            [("user_id", "=", self.env.user.id)],
            limit=1,
        )
        return employee.id if employee else False

    @api.model
    def _default_department_id(self):
        employee = self.env["hr.employee"].sudo().search(
            [("user_id", "=", self.env.user.id)],
            limit=1,
        )
        return employee.department_id.id if employee and employee.department_id else False

    @api.depends("meeting_date")
    def _compute_day_name(self):
        mapping = {
            0: "Senin",
            1: "Selasa",
            2: "Rabu",
            3: "Kamis",
            4: "Jumat",
            5: "Sabtu",
            6: "Minggu",
        }
        for rec in self:
            rec.day_name = mapping.get(rec.meeting_date.weekday(), "") if rec.meeting_date else ""

    @api.depends("participant_ids")
    def _compute_participant_names(self):
        for rec in self:
            rec.participant_names = ", ".join(
                "%s (%s)" % (participant.name, participant.initial_name)
                if participant.initial_name
                else participant.name
                for participant in rec.participant_ids
            )

    def get_note_taker_display(self):
        self.ensure_one()
        if not self.note_taker_id:
            return "-"
        if self.note_taker_id.initial_name:
            return "%s (%s)" % (
                self.note_taker_id.name,
                self.note_taker_id.initial_name,
            )
        return self.note_taker_id.name

    def _get_department_manager_approver(self):
        self.ensure_one()
        return self.department_id.manager_id.user_id

    def _get_effective_approver(self):
        self.ensure_one()
        return self.approver_id or self._get_department_manager_approver()

    def _get_follow_up_meeting_date(self):
        self.ensure_one()
        return (self.meeting_date + timedelta(days=7)) if self.meeting_date else fields.Date.context_today(self)

    def _get_follow_up_title(self):
        self.ensure_one()
        title = (self.title or self.agenda or _("Meeting")).strip()
        match = re.search(r" - Follow Up (\d+)$", title)
        if match:
            number = int(match.group(1)) + 1
            base_title = title[: match.start()]
        else:
            number = 1
            base_title = title
        return _("%s - Follow Up %s") % (base_title, number)

    def _has_pending_carry_forward_items(self):
        self.ensure_one()
        if not self.carry_forward_source_id:
            return False
        carried_previous_ids = set(self.line_ids.mapped("previous_line_id").ids)
        return bool(
            self.carry_forward_source_id.line_ids.filtered(
                lambda line: line.line_type == "item"
                and line._get_progress_status_value() not in ("done", "cancelled")
                and line.id not in carried_previous_ids
            )
        )

    @api.depends("line_ids", "line_ids.change_log_ids", "line_ids.carried_forward")
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids.filtered(lambda line: line.line_type == "item"))
            rec.change_count = sum(len(line.change_log_ids) for line in rec.line_ids)
            rec.carry_forward_count = len(rec.line_ids.filtered("carried_forward"))

    @api.depends(
        "state",
        "note_taker_id",
        "participant_ids",
        "approver_id",
    )
    @api.depends_context("uid")
    def _compute_permissions(self):
        for rec in self:
            is_admin = self.env.user.has_group("np_meeting_minutes.group_meeting_minutes_admin")
            effective_approver = rec._get_effective_approver()
            is_note_taker = rec.note_taker_id.user_id == self.env.user
            is_participant = self.env.user in rec.participant_ids.mapped("user_id")
            is_approver = effective_approver == self.env.user
            can_approve = bool(
                is_admin
                or (
                    is_approver
                    and rec.state == "waiting_approval"
                )
            )
            can_edit = bool(
                is_admin
                or (
                    (is_note_taker or is_participant or is_approver)
                    and rec.state in ("draft", "rejected")
                )
            )
            rec.is_admin = is_admin
            rec.can_edit_meeting = can_edit
            rec.can_submit_approval = bool(can_edit and rec.line_ids)
            rec.can_approve = can_approve
            rec.can_reset = bool(is_admin or is_note_taker or is_approver)
            rec.can_carry_forward = bool(can_edit and rec._has_pending_carry_forward_items())

    def _is_current_user_collaborator(self):
        self.ensure_one()
        if self.env.user.has_group("np_meeting_minutes.group_meeting_minutes_admin"):
            return True
        effective_approver = self._get_effective_approver()
        return bool(
            self.note_taker_id.user_id == self.env.user
            or self.env.user in self.participant_ids.mapped("user_id")
            or effective_approver == self.env.user
        )

    @api.constrains("start_time", "end_time")
    def _check_time_range(self):
        for rec in self:
            if rec.start_time and rec.end_time and rec.end_time < rec.start_time:
                raise UserError(_("Jam selesai harus lebih besar atau sama dengan jam mulai."))

    @api.onchange("note_taker_id")
    def _onchange_note_taker_id(self):
        for rec in self:
            if rec.note_taker_id and rec.note_taker_id.department_id and not rec.department_id:
                rec.department_id = rec.note_taker_id.department_id

    @api.onchange("department_id")
    def _onchange_department_id(self):
        for rec in self:
            department_approver = rec._get_department_manager_approver()
            if rec.department_id and department_approver:
                rec.approver_id = department_approver

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = sequence.next_by_code("np.meeting.minutes") or _("New")
            vals.setdefault("requested_by", self.env.user.id)
            if not vals.get("department_id") and vals.get("note_taker_id"):
                employee = self.env["hr.employee"].sudo().browse(vals["note_taker_id"])
                vals["department_id"] = employee.department_id.id
            if vals.get("department_id") and not vals.get("approver_id"):
                department = self.env["hr.department"].sudo().browse(vals["department_id"])
                approver = department.manager_id.user_id
                vals["approver_id"] = approver.id
        return super().create(vals_list)

    def write(self, vals):
        self._ensure_can_edit(vals)
        if "department_id" in vals and not vals.get("approver_id"):
            department = self.env["hr.department"].sudo().browse(vals["department_id"])
            approver = department.manager_id.user_id
            vals["approver_id"] = approver.id
        if "note_taker_id" in vals and "department_id" not in vals:
            employee = self.env["hr.employee"].sudo().browse(vals["note_taker_id"])
            if employee.department_id:
                vals["department_id"] = employee.department_id.id
                department_approver = employee.department_id.manager_id.user_id
                if not vals.get("approver_id") and department_approver:
                    vals["approver_id"] = department_approver.id
        return super().write(vals)

    def _ensure_can_edit(self, vals=False):
        vals = vals or {}
        bypass_fields = {
            "state",
            "approved_by",
            "approved_date",
            "rejected_by",
            "rejected_date",
            "approval_note",
            "export_file",
            "export_filename",
        }
        if set(vals).issubset(bypass_fields):
            return
        for rec in self:
            if rec.is_admin:
                continue
            is_note_taker = rec.note_taker_id.user_id == self.env.user
            is_participant = self.env.user in rec.participant_ids.mapped("user_id")
            is_approver = rec._get_effective_approver() == self.env.user
            if not (is_note_taker or is_participant or is_approver):
                raise AccessError(_("Hanya notulis, peserta, atau approver yang dapat mengubah data ini."))
            if rec.state not in ("draft", "rejected"):
                raise UserError(_("Meeting yang sudah disubmit tidak dapat diubah langsung."))

    def unlink(self):
        for rec in self:
            if rec.is_admin:
                continue
            if not rec._is_current_user_collaborator():
                raise AccessError(_("Hanya notulis, peserta, atau approver yang dapat menghapus data ini."))
        return super().unlink()

    def _ensure_submit_requirements(self):
        for rec in self:
            if not rec.note_taker_id:
                raise UserError(_("Notulis wajib diisi."))
            if not rec.department_id:
                raise UserError(_("Divisi wajib diisi."))
            effective_approver = rec._get_effective_approver()
            if not effective_approver and not rec.department_id.manager_id:
                raise UserError(_("Manager divisi belum diatur pada divisi ini."))
            if not effective_approver:
                raise UserError(
                    _("Approver belum ditentukan atau belum terhubung ke user Odoo.")
                )
            if not rec.line_ids:
                raise UserError(_("Pembahasan meeting masih kosong."))

    def _send_submit_approval_notification(self):
        self.ensure_one()
        approver = self._get_effective_approver()
        partner = approver.partner_id
        email_to = approver.email or partner.email
        if not partner:
            raise UserError(_("User approver belum memiliki partner kontak."))
        if not email_to:
            raise UserError(
                _("Email approver belum diisi pada user yang dipilih, jadi notifikasi tidak bisa dikirim.")
            )

        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        meeting_url = "%s/web#id=%s&model=np.meeting.minutes&view_type=form" % (
            base_url.rstrip("/"),
            self.id,
        ) if base_url else ""
        meeting_date = self._format_indonesian_date(self.meeting_date) if self.meeting_date else "-"
        subject = _("Approval Notulen Meeting %s") % (self.name or self.title or "")
        body_html = """
            <p>Yth. {approver_name},</p>
            <p>Notulen meeting berikut menunggu approval Anda:</p>
            <ul>
                <li><strong>No. Notulen:</strong> {name}</li>
                <li><strong>Judul:</strong> {title}</li>
                <li><strong>Agenda:</strong> {agenda}</li>
                <li><strong>Divisi:</strong> {department}</li>
                <li><strong>Tanggal:</strong> {meeting_date}</li>
                <li><strong>Notulis:</strong> {note_taker}</li>
            </ul>
            <p>Silakan buka notulen untuk meninjau dan memberikan approval.</p>
            {link_html}
        """.format(
            approver_name=escape(approver.name or "-"),
            name=escape(self.name or "-"),
            title=escape(self.title or "-"),
            agenda=escape(self.agenda or "-"),
            department=escape(self.department_id.display_name or "-"),
            meeting_date=escape(meeting_date),
            note_taker=escape(self.get_note_taker_display()),
            link_html=(
                '<p><a href="%s">Buka Notulen Meeting</a></p>' % escape(meeting_url)
                if meeting_url
                else ""
            ),
        )
        self.message_post(
            body=_("Permintaan approval dikirim ke approver: %s") % approver.name,
            subtype_xmlid="mail.mt_note",
        )
        self.env["mail.mail"].sudo().create(
            {
                "subject": subject,
                "body_html": body_html,
                "email_to": email_to,
                "recipient_ids": [(4, partner.id)],
                "model": self._name,
                "res_id": self.id,
                "auto_delete": True,
            }
        ).send()

    def _ensure_can_approve(self):
        for rec in self:
            if rec.is_admin:
                continue
            if not rec.can_approve:
                raise AccessError(_("Hanya approver meeting yang dapat melakukan approval."))

    def action_submit_approval(self):
        for rec in self:
            if rec.state not in ("draft", "rejected"):
                raise UserError(_("Hanya meeting draft atau ditolak yang bisa disubmit."))
            rec._ensure_submit_requirements()
            approver = rec._get_effective_approver()
            rec.write(
                {
                    "approver_id": approver.id if approver else False,
                    "state": "waiting_approval",
                    "approved_by": False,
                    "approved_date": False,
                    "rejected_by": False,
                    "rejected_date": False,
                }
            )
            rec._send_submit_approval_notification()
        return True

    def action_approve(self):
        for rec in self:
            if rec.state != "waiting_approval":
                raise UserError(_("Meeting ini tidak berada pada tahap approval."))
            rec._ensure_can_approve()
            rec.write(
                {
                    "state": "approved",
                    "approved_by": self.env.user.id,
                    "approved_date": fields.Datetime.now(),
                    "rejected_by": False,
                    "rejected_date": False,
                }
            )
        return True

    def action_reject(self):
        for rec in self:
            if rec.state != "waiting_approval":
                raise UserError(_("Meeting ini tidak berada pada tahap approval."))
            rec._ensure_can_approve()
            rec.write(
                {
                    "state": "rejected",
                    "rejected_by": self.env.user.id,
                    "rejected_date": fields.Datetime.now(),
                }
            )
        return True

    def action_done(self):
        for rec in self:
            if rec.state not in ("approved", "done"):
                raise UserError(_("Meeting hanya bisa diselesaikan setelah disetujui."))
            rec.write({"state": "done"})
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if not rec.can_reset and not rec.is_admin:
                raise AccessError(_("Anda tidak memiliki hak untuk mengembalikan meeting ke draft."))
            rec.write({"state": "draft"})
        return True

    def action_view_changes(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Riwayat Perubahan"),
            "res_model": "np.meeting.minutes.line.change",
            "view_mode": "list,form",
            "domain": [("meeting_id", "=", self.id)],
            "context": {"default_meeting_id": self.id},
        }

    def action_view_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pembahasan Meeting"),
            "res_model": "np.meeting.minutes.line",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("np_meeting_minutes.view_np_meeting_minutes_line_list").id, "list"),
                (self.env.ref("np_meeting_minutes.view_np_meeting_minutes_line_form").id, "form"),
            ],
            "search_view_id": self.env.ref("np_meeting_minutes.view_np_meeting_minutes_line_search").id,
            "domain": [("meeting_id", "=", self.id)],
            "context": {
                "default_meeting_id": self.id,
                "search_default_group_parent": 0,
            },
            "target": "current",
        }

    def action_print_web(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "name": _("Print Web"),
            "url": "/np_meeting_minutes/%s/print_web" % self.id,
            "target": "new",
        }

    def action_create_follow_up_meeting(self):
        self.ensure_one()
        if not self.line_ids.filtered(lambda line: line.line_type == "item" and line._get_progress_status_value() not in ("done", "cancelled")):
            raise UserError(_("Meeting ini tidak memiliki open item untuk dibawa ke meeting lanjutan."))

        follow_up = self.create(
            {
                "title": self._get_follow_up_title(),
                "agenda": self.agenda,
                "meeting_date": self._get_follow_up_meeting_date(),
                "location": self.location,
                "department_id": self.department_id.id,
                "note_taker_id": self.note_taker_id.id,
                "participant_ids": [(6, 0, self.participant_ids.ids)],
                "approver_id": self.approver_id.id,
                "carry_forward_source_id": self.id,
                "start_time": self.start_time,
                "end_time": self.end_time,
            }
        )
        follow_up.action_carry_forward_items()
        return {
            "type": "ir.actions.act_window",
            "name": _("Notulen Meeting"),
            "res_model": "np.meeting.minutes",
            "res_id": follow_up.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_carry_forward_items(self):
        line_model = self.env["np.meeting.minutes.line"]
        for rec in self:
            if rec.state not in ("draft", "rejected"):
                raise UserError(_("Carry forward hanya bisa dilakukan saat meeting masih draft atau ditolak."))
            if not rec.carry_forward_source_id:
                raise UserError(_("Silakan pilih sumber carry forward terlebih dahulu."))
            source = rec.carry_forward_source_id
            carried_previous_ids = set(rec.line_ids.mapped("previous_line_id").ids)
            pending_lines = source.line_ids.filtered(
                lambda line: line.line_type == "item"
                and line._get_progress_status_value() not in ("done", "cancelled")
                and line.id not in carried_previous_ids
            )
            if not pending_lines:
                raise UserError(_("Tidak ada item open dari meeting sumber yang perlu dibawa."))

            lines_to_copy = self.env["np.meeting.minutes.line"]
            for pending_line in pending_lines:
                current = pending_line
                while current and current.line_type == "item":
                    lines_to_copy |= current
                    current = current.parent_line_id

            section_sequence_map = {}
            created_line_map = {}
            for source_line in source.line_ids.sorted(key=lambda line: (line.sequence, line.id)):
                if source_line.line_type == "section":
                    existing_section = rec.line_ids.filtered(
                        lambda line: line.line_type == "section"
                        and line.section_title == source_line.section_title
                    )[:1]
                    if not existing_section:
                        existing_section = line_model.create(
                            {
                                "meeting_id": rec.id,
                                "sequence": source_line.sequence,
                                "line_type": "section",
                                "section_title": source_line.section_title,
                            }
                        )
                    section_sequence_map[source_line.sequence] = existing_section.sequence
                    continue
                if source_line not in lines_to_copy:
                    continue
                new_sequence = source_line.sequence
                section_candidates = [seq for seq in section_sequence_map if seq <= source_line.sequence]
                if section_candidates:
                    new_sequence = max(section_candidates) + 1
                new_line = line_model.create(
                    {
                        "meeting_id": rec.id,
                        "sequence": new_sequence,
                        "line_type": "item",
                        "number": source_line.number,
                        "topic": source_line.topic,
                        "discussion": source_line.discussion,
                        "owner_ids": [(6, 0, source_line.owner_ids.ids)],
                        "parent_line_id": created_line_map.get(source_line.parent_line_id.id),
                        "target_type": source_line._get_target_value(),
                        "progress_status": source_line._get_progress_status_value(),
                        "status": source_line.status,
                        "progress_note": source_line.progress_note,
                        "checklist_item_ids": [
                            (
                                0,
                                0,
                                {
                                    "sequence": item.sequence,
                                    "check_type": item.check_type,
                                    "content": item.content,
                                },
                            )
                            for item in source_line.checklist_item_ids.sorted(key=lambda item: (item.check_type, item.sequence, item.id))
                        ],
                        "previous_line_id": source_line.id,
                        "carried_forward": True,
                    }
                )
                created_line_map[source_line.id] = new_line.id
            rec._rebuild_follow_up_structure()
        return True

    def _rebuild_follow_up_structure(self):
        line_model = self.env["np.meeting.minutes.line"]
        for rec in self:
            source = rec.carry_forward_source_id
            if not source:
                continue

            linked_lines = rec.line_ids.filtered(lambda line: line.line_type == "item" and line.previous_line_id)
            if not linked_lines:
                continue

            source_section_map = {}
            current_section = False
            for source_line in source.line_ids.sorted(key=lambda line: (line.sequence, line.id)):
                if source_line.line_type == "section":
                    current_section = source_line
                    continue
                source_section_map[source_line.id] = current_section

            required_source_lines = line_model
            for line in linked_lines:
                current = line.previous_line_id
                while current and current.line_type == "item":
                    required_source_lines |= current
                    current = current.parent_line_id

            target_section_map = {}
            source_to_current = {
                line.previous_line_id.id: line
                for line in rec.line_ids.filtered(lambda item: item.line_type == "item" and item.previous_line_id)
            }

            for source_line in required_source_lines.sorted(
                key=lambda line: (line.get_nesting_level(), line.sequence, line.id)
            ):
                source_section = source_section_map.get(source_line.id)
                if source_section:
                    target_section = target_section_map.get(source_section.id)
                    if not target_section:
                        target_section = rec.line_ids.filtered(
                            lambda line: line.line_type == "section"
                            and line.section_title == source_section.section_title
                        )[:1]
                    if not target_section:
                        target_section = line_model.create(
                            {
                                "meeting_id": rec.id,
                                "sequence": source_section.sequence,
                                "line_type": "section",
                                "section_title": source_section.section_title,
                            }
                        )
                    target_section_map[source_section.id] = target_section

                parent_line = source_to_current.get(source_line.parent_line_id.id)
                target_line = source_to_current.get(source_line.id)
                structural_vals = {
                    "sequence": source_line.sequence,
                    "number": source_line.number,
                    "parent_line_id": parent_line.id if parent_line else False,
                }
                if target_line:
                    target_line.write(structural_vals)
                    continue

                new_line = line_model.create(
                    {
                        "meeting_id": rec.id,
                        "sequence": source_line.sequence,
                        "line_type": "item",
                        "number": source_line.number,
                        "topic": source_line.topic,
                        "discussion": source_line.discussion,
                        "owner_ids": [(6, 0, source_line.owner_ids.ids)],
                        "parent_line_id": parent_line.id if parent_line else False,
                        "target_type": source_line._get_target_value(),
                        "progress_status": source_line._get_progress_status_value(),
                        "status": source_line.status,
                        "progress_note": source_line.progress_note,
                        "checklist_item_ids": [
                            (
                                0,
                                0,
                                {
                                    "sequence": item.sequence,
                                    "check_type": item.check_type,
                                    "content": item.content,
                                },
                            )
                            for item in source_line.checklist_item_ids.sorted(key=lambda item: (item.check_type, item.sequence, item.id))
                        ],
                        "previous_line_id": source_line.id,
                        "carried_forward": True,
                    }
                )
                source_to_current[source_line.id] = new_line

    def action_rebuild_follow_up_structure(self):
        for rec in self:
            if rec.state not in ("draft", "rejected"):
                raise UserError(_("Perbaikan struktur hanya bisa dilakukan saat meeting masih draft atau ditolak."))
            if not rec.carry_forward_source_id:
                raise UserError(_("Meeting ini tidak memiliki sumber carry forward."))
            rec._rebuild_follow_up_structure()
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def _get_export_base_name(self):
        self.ensure_one()
        return (self.name or self.title or "notulen_meeting").replace("/", "-")

    def _prepare_download(self, content, filename, mimetype):
        self.ensure_one()
        self.write(
            {
                "export_file": base64.b64encode(content),
                "export_filename": filename,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content?model=np.meeting.minutes&id=%s&field=export_file&filename_field=export_filename&download=true" % self.id,
            "target": "self",
        }

    def action_export_excel(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError as exc:
            raise UserError(_("Library xlsxwriter tidak tersedia di server Odoo.")) from exc

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        sheet = workbook.add_worksheet("Notulen")

        title_fmt = workbook.add_format({"bold": True, "font_size": 14})
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})
        cell_fmt = workbook.add_format({"text_wrap": True, "valign": "top", "border": 1})
        section_fmt = workbook.add_format({"bold": True, "border": 1})

        sheet.set_column("A:A", 8)
        sheet.set_column("B:B", 50)
        sheet.set_column("C:C", 22)
        sheet.set_column("D:D", 18)
        sheet.set_column("E:E", 15)

        row = 0
        sheet.write(row, 0, "NOTULEN RAPAT", title_fmt)
        row += 2
        sheet.write(row, 0, "No. Notulen")
        sheet.write(row, 1, self.name or "-")
        row += 1
        sheet.write(row, 0, "Agenda")
        sheet.write(row, 1, self.agenda or self.title or "-")
        row += 1
        sheet.write(row, 0, "Hari / Tanggal")
        sheet.write(row, 1, self.get_meeting_date_display())
        row += 1
        sheet.write(row, 0, "Pukul")
        sheet.write(row, 1, self.get_meeting_time_display())
        row += 1
        sheet.write(row, 0, "Tempat")
        sheet.write(row, 1, self.location or "-")
        row += 1
        sheet.write(row, 0, "Notulis")
        sheet.write(row, 1, self.get_note_taker_display())
        row += 1
        sheet.write(row, 0, "Peserta")
        sheet.write(row, 1, self.participant_names or "-")
        row += 2

        headers = ["No", "Pembahasan", "Oleh", "Target", "Status"]
        for col, header in enumerate(headers):
            sheet.write(row, col, header, header_fmt)
        row += 1

        for line in self.line_ids.sorted(key=lambda item: (item.sequence, item.id)):
            if line.line_type == "section":
                section_text = line.section_title or "-"
                if line.discussion:
                    section_text = "%s\n%s" % (section_text, line.discussion)
                sheet.merge_range(row, 0, row, 4, section_text, section_fmt)
                row += 1
                continue
            if line.line_type != "item" or line.parent_line_id:
                continue
            outline_rows = line.get_report_outline_rows()
            if outline_rows:
                discussion_parts = [line.topic or ""]
                if line.discussion:
                    discussion_parts.append(line.discussion)
                target_lines = [line._get_target_label() or ""]
                status_lines = [line._get_progress_status_label() or ""]
                owner_lines = [line.owner_names or ""]
                for outline_row in outline_rows:
                    indent = "  " * max(outline_row["level"] - 1, 0)
                    marker = outline_row["marker"] or ""
                    topic = outline_row["topic"] or ""
                    discussion_parts.append("%s%s %s" % (indent, marker, topic))
                    if outline_row["discussion"]:
                        discussion_parts.append("%s  %s" % (indent, outline_row["discussion"]))
                    if outline_row["has_table"]:
                        discussion_parts.extend(
                            "%s  %s" % (indent, table_line)
                            for table_line in self._build_table_text_lines(
                                outline_row["table_title"],
                                outline_row["table_columns"],
                                outline_row["table_rows"],
                            )
                        )
                    discussion_parts.extend(
                        "%s%s" % (indent, line_text)
                        for line_text in self._build_checklist_text_lines(
                            "Update",
                            outline_row["update_items"],
                            outline_row["progress_note"],
                        )
                    )
                    discussion_parts.extend(
                        "%s%s" % (indent, line_text)
                        for line_text in self._build_checklist_text_lines(
                            "Note",
                            outline_row["note_items"],
                        )
                    )
                    if outline_row["change_summary"]:
                        discussion_parts.append("%s  Perubahan:" % indent)
                        discussion_parts.append("%s  %s" % (indent, outline_row["change_summary"]))
                    if outline_row["is_leaf"]:
                        owner_lines.append(outline_row["owner"] or "")
                        target_lines.append(outline_row["target"] or "")
                        status_lines.append(outline_row["status"] or "")
                    else:
                        owner_lines.append(outline_row["owner"] or "")
                        target_lines.append("")
                        status_lines.append("")

                sheet.write(row, 0, line.number or "-", cell_fmt)
                sheet.write(row, 1, "\n".join(part for part in discussion_parts if part is not None), cell_fmt)
                sheet.write(row, 2, "\n".join(owner_lines), cell_fmt)
                sheet.write(row, 3, "\n".join(target_lines), cell_fmt)
                sheet.write(row, 4, "\n".join(status_lines), cell_fmt)
                row += 1
                continue

            discussion_parts = [line.topic or "-"]
            if line.discussion:
                discussion_parts.append(line.discussion)
            if line.has_table_content():
                discussion_parts.extend(
                    self._build_table_text_lines(
                        line.table_title,
                        line.get_active_table_columns(),
                        line.get_table_rows(),
                    )
                )
            discussion_parts.extend(
                self._build_checklist_text_lines(
                    "Update",
                    line.get_update_items(),
                    line.progress_note,
                )
            )
            discussion_parts.extend(
                self._build_checklist_text_lines(
                    "Note",
                    line.get_note_items(),
                )
            )
            if line.change_summary:
                discussion_parts.append("Perubahan:\n%s" % line.change_summary)
            sheet.write(row, 0, line.number or "-", cell_fmt)
            sheet.write(row, 1, "\n\n".join(discussion_parts), cell_fmt)
            sheet.write(row, 2, line.owner_names or "-", cell_fmt)
            sheet.write(row, 3, line._get_target_label(), cell_fmt)
            sheet.write(row, 4, line._get_progress_status_label(), cell_fmt)
            row += 1

        workbook.close()
        buffer.seek(0)
        filename = "%s.xlsx" % self._get_export_base_name()
        return self._prepare_download(
            buffer.getvalue(),
            filename,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def action_export_word(self):
        self.ensure_one()
        rows_html = []
        for line in self.line_ids.sorted(key=lambda item: (item.sequence, item.id)):
            if line.line_type == "section":
                section_html = escape(line.section_title or "-")
                if line.discussion:
                    section_html = "%s<br/><span style='font-weight:400;'>%s</span>" % (
                        section_html,
                        escape(line.discussion).replace("\n", "<br/>"),
                    )
                rows_html.append(
                    "<tr><td colspan='5' style='font-weight:bold;'>%s</td></tr>" % section_html
                )
                continue
            if line.line_type != "item" or line.parent_line_id:
                continue
            outline_rows = line.get_report_outline_rows()
            if outline_rows:
                child_blocks = []
                owner_blocks = ["<div style='margin-top:5px;'>%s</div>" % escape(line.owner_names or "")]
                target_blocks = ["<div style='margin-top:5px;'>%s</div>" % escape(line._get_target_label() or "")]
                status_blocks = ["<div style='margin-top:5px;'>%s</div>" % escape(line._get_progress_status_label() or "")]
                for outline_row in outline_rows:
                    left_number = 22 + ((outline_row["level"] - 1) * 16)
                    left_body = 22 + ((outline_row["level"] - 1) * 16)
                    child_parts = [
                        "<div style='margin-top:5px; padding-left:%spx;'><span style='display:inline-block; white-space:nowrap; vertical-align:top; padding-right:10px;'>%s</span><span style='display:inline; vertical-align:top;'>%s</span></div>"
                        % (left_number, escape(outline_row["marker"] or ""), escape(outline_row["topic"] or "")),
                    ]
                    if outline_row["discussion"]:
                        child_parts.append(
                            "<div style='padding-left:%spx;'>%s</div>"
                            % (left_body + 18, escape(outline_row["discussion"]).replace("\n", "<br/>"))
                        )
                    if outline_row["has_table"]:
                        child_parts.append(
                            "<div style='padding-left:%spx;'>%s</div>"
                            % (
                                left_body + 18,
                                self._build_table_html(
                                    outline_row["table_title"],
                                    outline_row["table_columns"],
                                    outline_row["table_rows"],
                                ),
                            )
                        )
                    update_html = self._build_checklist_html(
                        "Update",
                        outline_row["update_items"],
                        outline_row["progress_note"],
                    )
                    if update_html:
                        child_parts.append(
                            "<div style='padding-left:%spx;'>%s</div>"
                            % (left_body + 18, update_html)
                        )
                    note_html = self._build_checklist_html(
                        "Note",
                        outline_row["note_items"],
                    )
                    if note_html:
                        child_parts.append(
                            "<div style='padding-left:%spx;'>%s</div>"
                            % (left_body + 18, note_html)
                        )
                    if outline_row["change_summary"]:
                        child_parts.append(
                            "<div style='padding-left:%spx;'><strong>Perubahan:</strong><br/>%s</div>"
                            % (left_body + 18, escape(outline_row["change_summary"]).replace("\n", "<br/>"))
                        )
                    child_blocks.append("".join(child_parts))
                    owner_blocks.append(
                        "<div style='margin-top:5px;'>%s</div>"
                        % escape(outline_row["owner"] or "")
                    )
                    target_blocks.append(
                        "<div style='margin-top:5px;'>%s</div>"
                        % escape(outline_row["target"] or "")
                    )
                    status_blocks.append(
                        "<div style='margin-top:5px;'>%s</div>"
                        % escape(outline_row["status"] or "")
                    )

                parent_notes = []
                if line.discussion:
                    parent_notes.append("<div>%s</div>" % escape(line.discussion).replace("\n", "<br/>"))
                if line.has_table_content():
                    parent_notes.append(
                        self._build_table_html(
                            line.table_title,
                            line.get_active_table_columns(),
                            line.get_table_rows(),
                        )
                    )
                discussion_html = (
                    "<div><strong>%s</strong></div>%s%s"
                    % (
                        escape(line.topic or ""),
                        "".join(parent_notes),
                        "".join(child_blocks),
                    )
                )
                rows_html.append(
                    """
                    <tr style="background:#fcfcfc;">
                        <td>{number}</td>
                        <td>{discussion}</td>
                        <td>{owners}</td>
                        <td>{target}</td>
                        <td>{status}</td>
                    </tr>
                    """.format(
                        number=escape(line.number or ""),
                        discussion=discussion_html,
                        owners="".join(owner_blocks),
                        target="".join(target_blocks),
                        status="".join(status_blocks),
                    )
                )
                continue

            parent_body = []
            if line.discussion:
                parent_body.append("<div>%s</div>" % escape(line.discussion or "-").replace("\n", "<br/>"))
            update_html = self._build_checklist_html(
                "Update",
                line.get_update_items(),
                line.progress_note,
            )
            if update_html:
                parent_body.append(update_html)
            note_html = self._build_checklist_html(
                "Note",
                line.get_note_items(),
            )
            if note_html:
                parent_body.append(note_html)
            if line.change_summary:
                parent_body.append(
                    "<div><strong>Perubahan:</strong><br/>%s</div>"
                    % escape(line.change_summary).replace("\n", "<br/>")
                )
            parent_discussion = "<div><strong>%s</strong></div>%s" % (
                escape(line.topic or "-"),
                "".join(parent_body),
            )
            rows_html.append(
                """
                <tr style="background:#fcfcfc;">
                    <td>{number}</td>
                    <td>{discussion}</td>
                    <td>{owners}</td>
                    <td>{target}</td>
                    <td>{status}</td>
                </tr>
                """.format(
                    number=escape(line.number or "-"),
                    discussion=parent_discussion,
                    owners=escape(line.owner_names or "-"),
                    target=escape(line._get_target_label()),
                    status=escape(line._get_progress_status_label()),
                )
            )

        document_html = """
        <html>
        <head>
            <meta charset="utf-8"/>
            <style>
                body {{ font-family: Arial, sans-serif; font-size: 11pt; }}
                h1 {{ text-align: center; font-size: 18pt; }}
                table {{ width: 100%; border-collapse: collapse; }}
                td, th {{ border: 1px solid #000; padding: 6px; vertical-align: top; }}
                th {{ text-align: center; }}
                .meta td {{ border: 0; padding: 2px 4px; }}
            </style>
        </head>
        <body>
            <h1>NOTULEN RAPAT</h1>
            <table class="meta">
                <tr><td style="width:25%;">No. Notulen</td><td>{name}</td></tr>
                <tr><td>Agenda</td><td>{agenda}</td></tr>
                <tr><td>Hari / Tanggal</td><td>{meeting_date}</td></tr>
                <tr><td>Pukul</td><td>{meeting_time}</td></tr>
                <tr><td>Tempat</td><td>{location}</td></tr>
                <tr><td>Notulis</td><td>{note_taker}</td></tr>
                <tr><td>Peserta</td><td>{participants}</td></tr>
            </table>
            <br/>
            <table>
                <thead>
                    <tr>
                        <th style="width:8%;">No</th>
                        <th>Pembahasan</th>
                        <th style="width:18%;">Oleh</th>
                        <th style="width:14%;">Target</th>
                        <th style="width:14%;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </body>
        </html>
        """.format(
            name=escape(self.name or "-"),
            agenda=escape(self.agenda or self.title or "-"),
            meeting_date=escape(self.get_meeting_date_display()),
            meeting_time=escape(self.get_meeting_time_display()),
            location=escape(self.location or "-"),
            note_taker=escape(self.get_note_taker_display()),
            participants=escape(self.participant_names or "-"),
            rows="".join(rows_html),
        )
        filename = "%s.doc" % self._get_export_base_name()
        return self._prepare_download(
            document_html.encode("utf-8"),
            filename,
            "application/msword",
        )

    def _format_time(self, float_time):
        hours = int(float_time or 0)
        minutes = int(round(((float_time or 0) - hours) * 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return f"{hours:02d}:{minutes:02d}"

    def _format_indonesian_date(self, value):
        months = {
            1: "Januari",
            2: "Februari",
            3: "Maret",
            4: "April",
            5: "Mei",
            6: "Juni",
            7: "Juli",
            8: "Agustus",
            9: "September",
            10: "Oktober",
            11: "November",
            12: "Desember",
        }
        if not value:
            return "-"
        return "%02d %s %s" % (value.day, months.get(value.month, ""), value.year)

    def get_meeting_time_display(self):
        self.ensure_one()
        if not self.start_time and not self.end_time:
            return "-"
        if self.end_time:
            return "%s - %s WIB" % (
                self._format_time(self.start_time),
                self._format_time(self.end_time),
            )
        return "%s WIB" % self._format_time(self.start_time)

    def get_meeting_date_display(self):
        self.ensure_one()
        if not self.meeting_date:
            return "-"
        return "%s, %s" % (self.day_name or "-", self._format_indonesian_date(self.meeting_date))

    def get_root_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: line.line_type == "item" and not line.parent_line_id
        ).sorted(key=lambda line: (line.sequence, line.id))

    def get_report_side_rows(self, line):
        line.ensure_one()
        return [
            {
                "target": row["target"],
                "status": row["status"],
            }
            for row in line.get_report_outline_rows()
        ]

    def _build_table_text_lines(self, title, columns, rows):
        lines = []
        if title:
            lines.append(title)
        if columns:
            lines.append(" | ".join((column.get("label") or "").strip() for column in columns))
        for row in rows:
            lines.append(" | ".join((value or "").strip() for value in row.get("values", [])))
        return lines

    def _build_checklist_text_lines(self, title, items, fallback_text=False):
        lines = []
        normalized_items = [(item or "").strip() for item in (items or []) if (item or "").strip()]
        fallback_text = (fallback_text or "").strip()
        if not normalized_items and not fallback_text:
            return lines
        lines.append("%s:" % title)
        if normalized_items:
            lines.extend("  \u2713 %s" % item for item in normalized_items)
        elif fallback_text:
            lines.append("  %s" % fallback_text)
        return lines

    def _build_checklist_html(self, title, items, fallback_text=False):
        normalized_items = [(item or "").strip() for item in (items or []) if (item or "").strip()]
        fallback_text = (fallback_text or "").strip()
        if not normalized_items and not fallback_text:
            return ""
        html_parts = [
            "<div style='margin-top:4px;'><strong>%s:</strong></div>" % escape(title),
        ]
        if normalized_items:
            for item in normalized_items:
                html_parts.append(
                    "<div style='padding-left:14px; margin-top:2px;'>&#10003; %s</div>"
                    % escape(item).replace("\n", "<br/>")
                )
        elif fallback_text:
            html_parts.append(
                "<div style='padding-left:14px; margin-top:2px;'>%s</div>"
                % escape(fallback_text).replace("\n", "<br/>")
            )
        return "".join(html_parts)

    def _build_table_html(self, title, columns, rows):
        if not columns and not rows:
            return ""
        html_parts = []
        if title:
            html_parts.append("<div style='margin-top:4px; font-weight:700;'>%s</div>" % escape(title))
        html_parts.append("<table style='width:100%%; border-collapse:collapse; margin-top:4px;'>")
        if columns:
            html_parts.append("<thead><tr>")
            for column in columns:
                html_parts.append(
                    "<th style='border:1px solid #000; padding:4px; text-align:center;'>%s</th>"
                    % escape(column.get("label") or "")
                )
            html_parts.append("</tr></thead>")
        html_parts.append("<tbody>")
        for row in rows:
            html_parts.append("<tr>")
            for value in row.get("values", []):
                html_parts.append(
                    "<td style='border:1px solid #000; padding:4px;'>%s</td>"
                    % escape(value or "")
                )
            html_parts.append("</tr>")
        html_parts.append("</tbody></table>")
        return "".join(html_parts)


class MeetingMinutesLine(models.Model):
    _name = "np.meeting.minutes.line"
    _description = "Baris Notulen Meeting"
    _inherit = ["mail.thread"]
    _order = "meeting_id desc, sequence asc, id asc"
    _rec_name = "line_name"

    TARGET_SELECTION = [
        ("info", "INFO"),
        ("action", "ACTION"),
    ]

    PROGRESS_STATUS_SELECTION = [
        ("monitoring", "Monitoring"),
        ("progress", "Progress"),
        ("plan", "Plan"),
        ("pending", "Pending"),
        ("waiting", "Waiting"),
        ("done", "Done"),
        ("cancelled", "Cancelled"),
    ]

    meeting_id = fields.Many2one(
        "np.meeting.minutes",
        string="Meeting",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [
            ("section", "Section"),
            ("item", "Item"),
        ],
        string="Tipe Baris",
        default="item",
        required=True,
        tracking=True,
    )
    line_name = fields.Char(
        string="Judul Baris",
        compute="_compute_line_name",
        store=True,
    )
    checklist_item_ids = fields.One2many(
        "np.meeting.minutes.line.checklist",
        "line_id",
        string="Checklist",
    )
    update_checklist_ids = fields.One2many(
        "np.meeting.minutes.line.checklist",
        "line_id",
        string="Checklist Update",
        domain=[("check_type", "=", "update")],
    )
    note_checklist_ids = fields.One2many(
        "np.meeting.minutes.line.checklist",
        "line_id",
        string="Checklist Note",
        domain=[("check_type", "=", "note")],
    )
    section_title = fields.Char(string="Judul Section", tracking=True)
    number = fields.Char(string="No", tracking=True)
    topic = fields.Char(string="Topik", tracking=True)
    parent_line_id = fields.Many2one(
        "np.meeting.minutes.line",
        string="Parent Topik",
        domain="[('meeting_id', '=', meeting_id), ('line_type', '=', 'item'), ('id', '!=', id)]",
        tracking=True,
    )
    child_line_ids = fields.One2many(
        "np.meeting.minutes.line",
        "parent_line_id",
        string="Sub Items",
    )
    is_subitem = fields.Boolean(string="Sub Item", compute="_compute_is_subitem", store=True)
    discussion = fields.Text(string="Pembahasan", tracking=True)
    use_table = fields.Boolean(string="Gunakan Tabel", tracking=True)
    table_title = fields.Char(string="Judul Tabel", tracking=True)
    table_col_1_label = fields.Char(string="Header Kolom 1", tracking=True)
    table_col_2_label = fields.Char(string="Header Kolom 2", tracking=True)
    table_col_3_label = fields.Char(string="Header Kolom 3", tracking=True)
    table_col_4_label = fields.Char(string="Header Kolom 4", tracking=True)
    table_col_5_label = fields.Char(string="Header Kolom 5", tracking=True)
    table_col_6_label = fields.Char(string="Header Kolom 6", tracking=True)
    table_header_guide = fields.Text(
        string="Panduan Header Tabel",
        compute="_compute_table_header_guide",
    )
    table_row_ids = fields.One2many(
        "np.meeting.minutes.line.table.row",
        "line_id",
        string="Baris Tabel",
    )
    owner_ids = fields.Many2many(
        "hr.employee",
        "np_meeting_minutes_line_hr_employee_rel",
        "line_id",
        "employee_id",
        string="Oleh",
        tracking=True,
    )
    owner_names = fields.Char(string="Oleh", compute="_compute_owner_names")
    target_type = fields.Selection(
        TARGET_SELECTION,
        string="Target",
        tracking=True,
    )
    target_date = fields.Date(string="Target", tracking=True)
    target_display = fields.Char(string="Target", compute="_compute_target_display")
    progress_status = fields.Selection(
        PROGRESS_STATUS_SELECTION,
        string="Status",
        tracking=True,
    )
    status = fields.Selection(
        TARGET_SELECTION + PROGRESS_STATUS_SELECTION,
        string="Legacy Status",
        default="info",
        tracking=True,
    )
    progress_note = fields.Text(string="Update / Progress", tracking=True)
    carried_forward = fields.Boolean(string="Carry Forward", readonly=True, tracking=True)
    previous_line_id = fields.Many2one(
        "np.meeting.minutes.line",
        string="Referensi Meeting Sebelumnya",
        domain="[('meeting_id', '!=', meeting_id), ('line_type', '=', 'item')]",
    )
    previous_status = fields.Char(string="Status Sebelumnya", compute="_compute_previous_summary")
    change_summary = fields.Text(string="Ringkasan Perubahan", compute="_compute_previous_summary")
    change_log_ids = fields.One2many(
        "np.meeting.minutes.line.change",
        "line_id",
        string="Riwayat Perubahan",
    )

    @api.onchange("line_type", "parent_line_id", "meeting_id")
    def _onchange_numbering_fields(self):
        for rec in self:
            if rec.line_type != "item" or rec.number:
                continue
            rec.number = rec._generate_next_number()

    @api.depends("owner_ids")
    def _compute_owner_names(self):
        for rec in self:
            rec.owner_names = ", ".join(
                owner.initial_name or owner.name for owner in rec.owner_ids
            )

    @api.depends("line_type", "number", "section_title", "topic")
    def _compute_line_name(self):
        for rec in self:
            if rec.line_type == "section":
                title = rec.section_title or _("Section")
                rec.line_name = _("[Section] %s") % title
                continue
            if rec.number and rec.topic:
                rec.line_name = "[%s] %s" % (rec.number, rec.topic)
            elif rec.topic:
                rec.line_name = rec.topic
            elif rec.number:
                rec.line_name = "[%s]" % rec.number
            else:
                rec.line_name = _("Baris Pembahasan")

    @api.depends("parent_line_id")
    def _compute_is_subitem(self):
        for rec in self:
            rec.is_subitem = bool(rec.parent_line_id)

    @api.depends("target_type", "target_date")
    def _compute_target_display(self):
        for rec in self:
            rec.target_display = rec._get_target_label()

    @api.depends(
        "table_col_1_label",
        "table_col_2_label",
        "table_col_3_label",
        "table_col_4_label",
        "table_col_5_label",
        "table_col_6_label",
    )
    def _compute_table_header_guide(self):
        for rec in self:
            headers = []
            for index in range(1, 7):
                label = getattr(rec, "table_col_%s_label" % index)
                if (label or "").strip():
                    headers.append("%s. %s" % (index, label.strip()))
            rec.table_header_guide = "\n".join(headers)

    @api.depends(
        "previous_line_id",
        "progress_status",
        "progress_note",
        "target_type",
        "status",
        "checklist_item_ids.check_type",
        "checklist_item_ids.content",
        "checklist_item_ids.sequence",
    )
    def _compute_previous_summary(self):
        for rec in self:
            if not rec.previous_line_id:
                rec.previous_status = "-"
                rec.change_summary = False
                continue
            previous = rec.previous_line_id
            rec.previous_status = previous._get_progress_status_label()
            diffs = []
            if previous._get_progress_status_value() != rec._get_progress_status_value():
                diffs.append(
                    _("Status: %(old)s -> %(new)s")
                    % {
                        "old": previous._get_progress_status_label(),
                        "new": rec._get_progress_status_label(),
                    }
                )
            if previous._get_target_value() != rec._get_target_value():
                diffs.append(
                    _("Target: %(old)s -> %(new)s")
                    % {
                        "old": previous._get_target_label(),
                        "new": rec._get_target_label(),
                    }
                )
            if previous._get_update_display_text() != rec._get_update_display_text():
                diffs.append(_("Update progress berubah."))
            if previous._get_note_display_text() != rec._get_note_display_text():
                diffs.append(_("Catatan note berubah."))
            rec.change_summary = "\n".join(diffs) if diffs else False

    @api.model_create_multi
    def create(self, vals_list):
        editable_meetings = self.env["np.meeting.minutes"]
        records_to_number = self.browse()
        for vals in vals_list:
            if vals.get("meeting_id"):
                editable_meetings |= self.env["np.meeting.minutes"].browse(vals["meeting_id"])
            vals.setdefault("status", False)
            if vals.get("line_type", "item") != "item":
                continue
            if vals.get("number"):
                continue
            temp_record = self.new(vals)
            vals["number"] = temp_record._generate_next_number()
        editable_meetings._ensure_can_edit()
        records = super().create(vals_list)
        records._create_change_logs_for_create()
        return records

    def write(self, vals):
        self.mapped("meeting_id")._ensure_can_edit(vals)
        if "target_type" in vals or "progress_status" in vals:
            vals.setdefault("status", False)
        tracked_fields = {
            "section_title",
            "number",
            "topic",
            "parent_line_id",
            "discussion",
            "target_type",
            "target_date",
            "progress_status",
            "status",
            "progress_note",
            "checklist_item_ids",
            "previous_line_id",
            "line_type",
            "carried_forward",
        }
        before_map = {}
        if tracked_fields.intersection(vals.keys()):
            for rec in self:
                before_map[rec.id] = rec._prepare_change_snapshot()
        result = super().write(vals)
        if before_map:
            self._create_change_logs_for_write(before_map)
        return result

    def unlink(self):
        self.mapped("meeting_id")._ensure_can_edit()
        return super().unlink()

    def _generate_next_number(self):
        self.ensure_one()
        meeting = self.meeting_id
        if not meeting and self._origin and self._origin.meeting_id:
            meeting = self._origin.meeting_id
        if not meeting:
            return "1"

        parent = self.parent_line_id
        if not parent and self._origin and self._origin.parent_line_id:
            parent = self._origin.parent_line_id

        siblings = meeting.line_ids.filtered(
            lambda line: line.line_type == "item"
            and line.id != self.id
            and line.parent_line_id == parent
        )
        max_index = 0
        for sibling in siblings:
            number = (sibling.number or "").strip()
            if not number:
                continue
            try:
                part = int(number.split(".")[-1])
            except ValueError:
                continue
            max_index = max(max_index, part)

        next_index = max_index + 1
        if parent and parent.number:
            return "%s.%s" % (parent.number, next_index)
        return str(next_index)

    def _prepare_change_snapshot(self):
        self.ensure_one()
        return {
            "line_type": self.line_type,
            "section_title": self.section_title,
            "number": self.number,
            "topic": self.topic,
            "parent_line_id": self.parent_line_id.id,
            "discussion": self.discussion,
            "use_table": self.use_table,
            "table_title": self.table_title,
            "table_col_1_label": self.table_col_1_label,
            "table_col_2_label": self.table_col_2_label,
            "table_col_3_label": self.table_col_3_label,
            "table_col_4_label": self.table_col_4_label,
            "table_col_5_label": self.table_col_5_label,
            "table_col_6_label": self.table_col_6_label,
            "owner_names": self.owner_names,
            "target_type": self.target_type,
            "target_date": self.target_date,
            "progress_status": self.progress_status,
            "status": self.status,
            "progress_note": self.progress_note,
            "update_display": self._get_update_display_text(),
            "note_display": self._get_note_display_text(),
            "previous_line_id": self.previous_line_id.id,
            "carried_forward": self.carried_forward,
        }

    def _get_target_value(self):
        self.ensure_one()
        if self.target_type:
            return self.target_type
        return False

    def _get_target_label(self):
        self.ensure_one()
        value = self._get_target_value()
        return dict(self.TARGET_SELECTION).get(value, "")

    def _get_progress_status_value(self):
        self.ensure_one()
        if self.progress_status:
            return self.progress_status
        return False

    def _get_progress_status_label(self):
        self.ensure_one()
        value = self._get_progress_status_value()
        return dict(self.PROGRESS_STATUS_SELECTION).get(value, "")

    def _get_status_label(self, value):
        return dict(self.PROGRESS_STATUS_SELECTION).get(value, value or "")

    def _get_checklist_items(self, check_type):
        self.ensure_one()
        return [
            (item.content or "").strip()
            for item in self.checklist_item_ids.filtered(lambda row: row.check_type == check_type).sorted(
                key=lambda row: (row.sequence, row.id)
            )
            if (item.content or "").strip()
        ]

    def get_update_items(self):
        self.ensure_one()
        return self._get_checklist_items("update")

    def get_note_items(self):
        self.ensure_one()
        return self._get_checklist_items("note")

    def _get_update_display_text(self):
        self.ensure_one()
        items = self.get_update_items()
        if items:
            return "\n".join(items)
        return (self.progress_note or "").strip()

    def _get_note_display_text(self):
        self.ensure_one()
        return "\n".join(self.get_note_items())

    def _build_change_message(self, before=False):
        self.ensure_one()
        if not before:
            if self.line_type == "section":
                return _("Baris section dibuat: %s") % (self.section_title or "-")
            return _("Item dibuat dengan status %s.") % self._get_progress_status_label()

        changes = []
        if before.get("line_type") != self.line_type:
            changes.append(_("Tipe baris berubah."))
        if before.get("section_title") != self.section_title:
            changes.append(_("Judul section diperbarui."))
        if before.get("number") != self.number:
            changes.append(_("Nomor pembahasan diperbarui."))
        if before.get("topic") != self.topic:
            changes.append(_("Topik diperbarui."))
        if before.get("parent_line_id") != self.parent_line_id.id:
            changes.append(_("Parent topik diperbarui."))
        if before.get("discussion") != self.discussion:
            changes.append(_("Isi pembahasan diperbarui."))
        if before.get("use_table") != self.use_table:
            changes.append(_("Penggunaan tabel diperbarui."))
        if before.get("table_title") != self.table_title:
            changes.append(_("Judul tabel diperbarui."))
        for index in range(1, 7):
            key = "table_col_%s_label" % index
            if before.get(key) != getattr(self, key):
                changes.append(_("Header tabel diperbarui."))
                break
        if before.get("target_type") != self._get_target_value():
            changes.append(
                _("Target berubah dari %(old)s ke %(new)s.")
                % {
                    "old": dict(self.TARGET_SELECTION).get(before.get("target_type"), "-"),
                    "new": self._get_target_label(),
                }
            )
        if before.get("progress_status") != self._get_progress_status_value():
            changes.append(
                _("Status berubah dari %(old)s ke %(new)s.")
                % {
                    "old": dict(self.PROGRESS_STATUS_SELECTION).get(before.get("progress_status"), "-"),
                    "new": self._get_progress_status_label(),
                }
            )
        if before.get("update_display") != self._get_update_display_text():
            changes.append(_("Catatan progress diperbarui."))
        if before.get("note_display") != self._get_note_display_text():
            changes.append(_("Catatan note diperbarui."))
        if before.get("previous_line_id") != self.previous_line_id.id:
            changes.append(_("Referensi meeting sebelumnya diperbarui."))
        if before.get("carried_forward") != self.carried_forward and self.carried_forward:
            changes.append(_("Item dibawa dari meeting sebelumnya."))
        return "\n".join(changes)

    def _create_change_logs_for_create(self):
        change_model = self.env["np.meeting.minutes.line.change"].sudo()
        for rec in self.filtered(lambda line: line.line_type in ("section", "item")):
            change_model.create(
                {
                    "meeting_id": rec.meeting_id.id,
                    "line_id": rec.id,
                    "change_type": "create",
                    "user_id": self.env.user.id,
                    "message": rec._build_change_message(),
                    "old_status": False,
                    "new_status": rec._get_progress_status_value(),
                    "old_target_type": False,
                    "new_target_type": rec._get_target_value(),
                }
            )

    def _create_change_logs_for_write(self, before_map):
        change_model = self.env["np.meeting.minutes.line.change"].sudo()
        for rec in self:
            before = before_map.get(rec.id)
            if not before:
                continue
            message = rec._build_change_message(before)
            if not message:
                continue
            change_model.create(
                {
                    "meeting_id": rec.meeting_id.id,
                    "line_id": rec.id,
                    "change_type": "update",
                    "user_id": self.env.user.id,
                    "message": message,
                    "old_status": before.get("progress_status"),
                    "new_status": rec._get_progress_status_value(),
                    "old_target_type": before.get("target_type"),
                    "new_target_type": rec._get_target_value(),
                }
            )

    def get_sorted_child_lines(self):
        self.ensure_one()
        return self.child_line_ids.sorted(key=lambda line: (line.sequence, line.id))

    def get_descendant_lines(self):
        self.ensure_one()
        descendants = self.env[self._name]
        for child in self.get_sorted_child_lines():
            descendants |= child
            descendants |= child.get_descendant_lines()
        return descendants

    def get_leaf_lines(self):
        self.ensure_one()
        children = self.get_sorted_child_lines()
        if not children:
            return self
        leaves = self.env[self._name]
        for child in children:
            leaves |= child.get_leaf_lines()
        return leaves.sorted(key=lambda line: (line.sequence, line.id))

    def get_nesting_level(self):
        self.ensure_one()
        level = 0
        current = self.parent_line_id
        while current:
            level += 1
            current = current.parent_line_id
        return level

    def get_table_columns(self):
        self.ensure_one()
        columns = []
        for index in range(1, 7):
            columns.append(
                {
                    "key": "col_%s" % index,
                    "label": getattr(self, "table_col_%s_label" % index) or "",
                }
            )
        return columns

    def get_active_table_columns(self):
        self.ensure_one()
        rows = self.table_row_ids.sorted(key=lambda row: (row.sequence, row.id))
        active_columns = []
        for column in self.get_table_columns():
            has_data = any(getattr(row, column["key"]) for row in rows)
            if (column["label"] or "").strip() or has_data:
                active_columns.append(column)
        return active_columns

    def get_table_rows(self):
        self.ensure_one()
        active_columns = self.get_active_table_columns()
        return [
            {
                "values": [getattr(row, column["key"]) or "" for column in active_columns],
            }
            for row in self.table_row_ids.sorted(key=lambda table_row: (table_row.sequence, table_row.id))
        ]

    def has_table_content(self):
        self.ensure_one()
        return bool(self.use_table and (self.get_active_table_columns() or self.table_row_ids))

    def get_report_outline_rows(self, base_level=False):
        self.ensure_one()
        base_level = self.get_nesting_level() if base_level is False else base_level
        rows = []
        for child in self.get_sorted_child_lines():
            relative_level = child.get_nesting_level() - base_level
            last_segment = (child.number or "").split(".")[-1] if child.number else ""
            marker = ("%s." % last_segment) if relative_level == 1 else "•"
            is_leaf = not bool(child.child_line_ids)
            rows.append(
                {
                    "level": relative_level,
                    "marker": marker,
                    "topic": child.topic or "",
                    "discussion": child.discussion or "",
                    "owner": child.owner_names or "",
                    "table_title": child.table_title or "",
                    "table_columns": child.get_active_table_columns(),
                    "table_rows": child.get_table_rows(),
                    "has_table": child.has_table_content(),
                    "progress_note": child.progress_note or "",
                    "update_items": child.get_update_items(),
                    "note_items": child.get_note_items(),
                    "change_summary": child.change_summary or "",
                    "target": child._get_target_label() if is_leaf else "",
                    "status": child._get_progress_status_label() if is_leaf else "",
                    "is_leaf": is_leaf,
                }
            )
            rows.extend(child.get_report_outline_rows(base_level=base_level))
        return rows

    def get_report_outline_rows(self, base_level=False):
        self.ensure_one()
        base_level = self.get_nesting_level() if base_level is False else base_level
        rows = []
        for child in self.get_sorted_child_lines():
            relative_level = child.get_nesting_level() - base_level
            last_segment = (child.number or "").split(".")[-1] if child.number else ""
            marker = child.number or ("%s." % last_segment if last_segment else "")
            is_leaf = not bool(child.child_line_ids)
            rows.append(
                {
                    "level": relative_level,
                    "marker": marker,
                    "topic": child.topic or "",
                    "discussion": child.discussion or "",
                    "owner": child.owner_names or "",
                    "table_title": child.table_title or "",
                    "table_columns": child.get_active_table_columns(),
                    "table_rows": child.get_table_rows(),
                    "has_table": child.has_table_content(),
                    "progress_note": child.progress_note or "",
                    "update_items": child.get_update_items(),
                    "note_items": child.get_note_items(),
                    "change_summary": child.change_summary or "",
                    "target": child._get_target_label() if is_leaf else "",
                    "status": child._get_progress_status_label() if is_leaf else "",
                    "is_leaf": is_leaf,
                }
            )
            rows.extend(child.get_report_outline_rows(base_level=base_level))
        return rows

    def action_add_subitem(self):
        self.ensure_one()
        if self.line_type != "item":
            raise UserError(_("Sub item hanya bisa dibuat dari baris item."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Tambah Sub Item"),
            "res_model": "np.meeting.minutes.line",
            "view_mode": "form",
            "view_id": self.env.ref("np_meeting_minutes.view_np_meeting_minutes_line_subitem_popup").id,
            "target": "new",
            "context": {
                "default_meeting_id": self.meeting_id.id,
                "default_line_type": "item",
                "default_parent_line_id": self.id,
                "default_owner_ids": [(6, 0, self.owner_ids.ids)],
                "default_target_type": self._get_target_value(),
                "default_progress_status": self._get_progress_status_value(),
                "default_status": self.status,
            },
        }

    def action_delete_line(self):
        for rec in self:
            lines_to_delete = rec
            if rec.line_type == "item":
                lines_to_delete |= rec.get_descendant_lines()
            lines_to_delete.unlink()
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }


class MeetingMinutesLineChange(models.Model):
    _name = "np.meeting.minutes.line.change"
    _description = "Riwayat Perubahan Notulen"
    _order = "create_date desc, id desc"

    meeting_id = fields.Many2one(
        "np.meeting.minutes",
        string="Meeting",
        required=True,
        ondelete="cascade",
    )
    line_id = fields.Many2one(
        "np.meeting.minutes.line",
        string="Baris Notulen",
        required=True,
        ondelete="cascade",
    )
    change_type = fields.Selection(
        [
            ("create", "Create"),
            ("update", "Update"),
        ],
        string="Tipe",
        required=True,
        default="update",
    )
    user_id = fields.Many2one("res.users", string="Diubah Oleh", readonly=True)
    message = fields.Text(string="Perubahan", required=True)
    old_status = fields.Selection(MeetingMinutesLine.PROGRESS_STATUS_SELECTION, string="Status Lama")
    new_status = fields.Selection(MeetingMinutesLine.PROGRESS_STATUS_SELECTION, string="Status Baru")
    old_target_type = fields.Selection(MeetingMinutesLine.TARGET_SELECTION, string="Target Lama")
    new_target_type = fields.Selection(MeetingMinutesLine.TARGET_SELECTION, string="Target Baru")


class MeetingMinutesLineChecklist(models.Model):
    _name = "np.meeting.minutes.line.checklist"
    _description = "Checklist Update atau Note Pembahasan"
    _order = "line_id, check_type, sequence, id"

    CHECK_TYPE_SELECTION = [
        ("update", "Update"),
        ("note", "Note"),
    ]

    line_id = fields.Many2one(
        "np.meeting.minutes.line",
        string="Baris Notulen",
        required=True,
        ondelete="cascade",
    )
    meeting_id = fields.Many2one(
        "np.meeting.minutes",
        string="Meeting",
        related="line_id.meeting_id",
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(default=10)
    check_type = fields.Selection(
        CHECK_TYPE_SELECTION,
        string="Tipe",
        required=True,
        default="update",
    )
    content = fields.Text(string="Isi", required=True)

    @api.model_create_multi
    def create(self, vals_list):
        self.env["np.meeting.minutes.line"].browse(
            [vals["line_id"] for vals in vals_list if vals.get("line_id")]
        ).mapped("meeting_id")._ensure_can_edit()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped("meeting_id")._ensure_can_edit(vals)
        return super().write(vals)

    def unlink(self):
        self.mapped("meeting_id")._ensure_can_edit()
        return super().unlink()


class MeetingMinutesLineTableRow(models.Model):
    _name = "np.meeting.minutes.line.table.row"
    _description = "Baris Tabel Pembahasan Notulen"
    _order = "line_id, sequence, id"

    line_id = fields.Many2one(
        "np.meeting.minutes.line",
        string="Baris Notulen",
        required=True,
        ondelete="cascade",
    )
    meeting_id = fields.Many2one(
        "np.meeting.minutes",
        string="Meeting",
        related="line_id.meeting_id",
        store=True,
        readonly=True,
    )
    header_1_label = fields.Char(related="line_id.table_col_1_label", readonly=True)
    header_2_label = fields.Char(related="line_id.table_col_2_label", readonly=True)
    header_3_label = fields.Char(related="line_id.table_col_3_label", readonly=True)
    header_4_label = fields.Char(related="line_id.table_col_4_label", readonly=True)
    header_5_label = fields.Char(related="line_id.table_col_5_label", readonly=True)
    header_6_label = fields.Char(related="line_id.table_col_6_label", readonly=True)
    sequence = fields.Integer(default=10)
    col_1 = fields.Char(string="Kolom 1")
    col_2 = fields.Char(string="Kolom 2")
    col_3 = fields.Char(string="Kolom 3")
    col_4 = fields.Char(string="Kolom 4")
    col_5 = fields.Char(string="Kolom 5")
    col_6 = fields.Char(string="Kolom 6")

    @api.model_create_multi
    def create(self, vals_list):
        self.env["np.meeting.minutes.line"].browse(
            [vals["line_id"] for vals in vals_list if vals.get("line_id")]
        ).mapped("meeting_id")._ensure_can_edit()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped("meeting_id")._ensure_can_edit(vals)
        return super().write(vals)

    def unlink(self):
        self.mapped("meeting_id")._ensure_can_edit()
        return super().unlink()
