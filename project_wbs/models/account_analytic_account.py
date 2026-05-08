# Copyright 2017-19 Eficent Business and IT Consulting Services S.L.
# Copyright 2017 Luxim d.o.o.
# Copyright 2017 Matmoz d.o.o.
# Copyright 2017 Deneroteam.
# Copyright 2017 Serpent Consulting Services Pvt. Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountAnalyticAccount(models.Model):
    _inherit = "account.analytic.account"
    _parent_name = "parent_id"
    _parent_store = True
    _order = "complete_wbs_code, id"

    parent_path = fields.Char(index=True, unaccent=False)
    parent_id = fields.Many2one(
        "account.analytic.account",
        string="Parent Analytic Account",
        default=lambda self: self.env.context.get("parent_id"),
        index=True,
        ondelete="restrict",
    )
    child_ids = fields.One2many(
        "account.analytic.account",
        "parent_id",
        string="Child Analytic Accounts",
    )
    wbs_indent = fields.Char(compute="_compute_wbs_indent", string="Level")
    complete_wbs_code = fields.Char(
        compute="_compute_complete_wbs_code",
        string="Full WBS Code",
        help="The full WBS code describes the full path of this component within the project WBS hierarchy",
        store=True,
    )
    complete_wbs_name = fields.Char(
        compute="_compute_complete_wbs_name",
        string="Full WBS Path",
        help="Full path in the WBS hierarchy",
        store=True,
    )
    project_ids = fields.One2many(
        "project.project",
        "account_id",
        string="Projects",
    )
    project_analytic_id = fields.Many2one(
        "account.analytic.account",
        compute="_compute_project_analytic_id",
        string="Root Analytic Account",
        store=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Project Manager",
        tracking=True,
        default=lambda self: self.env.context.get("user_id", self.env.user),
    )
    manager_id = fields.Many2one("res.users", string="Manager", tracking=True)
    account_class = fields.Selection(
        [
            ("project", "Project"),
            ("phase", "Phase"),
            ("deliverable", "Deliverable"),
            ("work_package", "Work Package"),
        ],
        string="Class",
        default="project",
        help="The classification allows you to create a proper project Work Breakdown Structure",
    )
    partner_id = fields.Many2one(default=lambda self: self.env.context.get("partner_id"))
    plan_id = fields.Many2one(
        default=lambda self: self.env["account.analytic.plan"]._get_all_plans()[0].id
    )

    @api.model
    def _next_wbs_code(self, record_id=None):
        code = self.env["ir.sequence"].next_by_code("project.wbs.analytic.code")
        if code:
            return code
        if record_id:
            return f"LEGACY-WBS-{record_id}"
        return "LEGACY-WBS-TMP"

    def get_child_accounts(self):
        return {account.id: True for account in self.search([("id", "child_of", self.ids)])}

    @api.depends("code", "parent_id.complete_wbs_code")
    def _compute_complete_wbs_code(self):
        for account in self:
            codes = []
            current = account
            while current:
                if current.code:
                    codes.insert(0, current.code)
                current = current.parent_id
            account.complete_wbs_code = f"[{' / '.join(codes)}]" if codes else ""

    @api.depends("name", "parent_id.complete_wbs_name")
    def _compute_complete_wbs_name(self):
        for account in self:
            names = []
            current = account
            while current:
                if current.name:
                    names.insert(0, current.name)
                current = current.parent_id
            account.complete_wbs_name = " / ".join(names)

    @api.depends("parent_id")
    def _compute_wbs_indent(self):
        for account in self:
            level = 0
            current = account.parent_id
            while current:
                level += 1
                current = current.parent_id
            account.wbs_indent = ">" * level if level else ""

    @api.depends("account_class", "parent_id", "parent_id.project_analytic_id")
    def _compute_project_analytic_id(self):
        for analytic in self:
            analytic.project_analytic_id = False
            current = analytic
            while current:
                if current.account_class == "project":
                    analytic.project_analytic_id = current
                    break
                current = current.parent_id

    @api.depends("name", "complete_wbs_name", "complete_wbs_code")
    def _compute_display_name(self):
        super()._compute_display_name()
        for account in self:
            if account.complete_wbs_name:
                label = account.complete_wbs_name.replace(" / ", "/")
                if account.complete_wbs_code:
                    label = f"{account.complete_wbs_code} {label}"
                account.display_name = label

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = self._next_wbs_code()
            if vals.get("parent_id"):
                parent = self.browse(vals["parent_id"])
                vals.setdefault("plan_id", parent.plan_id.id)
                vals.setdefault("company_id", parent.company_id.id)
                if parent.partner_id:
                    vals.setdefault("partner_id", parent.partner_id.id)
                if parent.user_id:
                    vals.setdefault("user_id", parent.user_id.id)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if {"parent_id", "code", "name"} & set(vals):
            self.browse(self.get_child_accounts().keys())._recompute_wbs_fields()
        if "active" in vals:
            for account in self:
                account.project_ids.filtered(
                    lambda project: project.active != account.active
                ).write({"active": account.active})
        return res

    def _recompute_wbs_fields(self):
        self._compute_complete_wbs_code()
        self._compute_complete_wbs_name()
        self._compute_wbs_indent()
        self._compute_project_analytic_id()
        self._compute_display_name()

    @api.onchange("parent_id")
    def _onchange_parent_id(self):
        if self.parent_id:
            self.plan_id = self.parent_id.plan_id
            self.company_id = self.parent_id.company_id
            if self.parent_id.partner_id and not self.partner_id:
                self.partner_id = self.parent_id.partner_id
            if self.parent_id.user_id and not self.user_id:
                self.user_id = self.parent_id.user_id

    def copy(self, default=None):
        if self.mapped("project_ids"):
            raise ValidationError(_("Duplicate the project instead of the Analytic Account"))
        default = dict(default or {})
        default["code"] = self._next_wbs_code(self.id)
        return super().copy(default)

    def code_get(self):
        return [(account.id, account.complete_wbs_code.strip("[]")) for account in self]

    _analytic_unique_wbs_code = models.Constraint(
        "UNIQUE (complete_wbs_code)",
        _("The full wbs code must be unique!"),
    )
