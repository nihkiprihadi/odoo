# Copyright 2017-19 Eficent Business and IT Consulting Services S.L.
# Copyright 2017 Luxim d.o.o.
# Copyright 2017 Matmoz d.o.o.
# Copyright 2017 Deneroteam.
# Copyright 2017 Serpent Consulting Services Pvt. Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models


class Project(models.Model):
    _inherit = "project.project"
    _description = "WBS element"
    _order = "complete_wbs_code, id"

    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Analytic Account",
        related="account_id",
        readonly=False,
        store=True,
        ondelete="restrict",
        index=True,
    )
    parent_id = fields.Many2one(
        related="account_id.parent_id",
        readonly=False,
        store=True,
    )
    child_ids = fields.One2many(
        related="account_id.child_ids",
        readonly=False,
    )
    project_child_complete_ids = fields.Many2many(
        comodel_name="project.project",
        string="Project Hierarchy",
        compute="_compute_child",
    )
    has_project_child_complete_ids = fields.Boolean(compute="_compute_has_child")
    wbs_indent = fields.Char(related="account_id.wbs_indent", readonly=False)
    complete_wbs_code = fields.Char(
        related="account_id.complete_wbs_code",
        string="WBS Code",
        store=True,
        readonly=False,
    )
    code = fields.Char(related="account_id.code", readonly=False)
    complete_wbs_name = fields.Char(related="account_id.complete_wbs_name", readonly=False)
    project_analytic_id = fields.Many2one(
        related="account_id.project_analytic_id",
        readonly=True,
        store=True,
    )
    account_class = fields.Selection(
        related="account_id.account_class",
        store=True,
        default="project",
        readonly=False,
    )

    def _get_project_analytic_wbs(self):
        result = {}
        for project in self:
            children = self.search([("account_id", "child_of", project.account_id.ids)])
            result[project.id] = {child.id: child.account_id.id for child in children}
        return result

    def _get_project_wbs(self):
        result = []
        projects_data = self._get_project_analytic_wbs()
        for values in projects_data.values():
            result.extend(values.keys())
        return result

    def code_get(self):
        return [(project.id, project.complete_wbs_code.strip("[]")) for project in self]

    @api.depends("name", "complete_wbs_name", "complete_wbs_code")
    def _compute_display_name(self):
        super()._compute_display_name()
        for project in self:
            if project.complete_wbs_name:
                label = project.complete_wbs_name.replace(" / ", "/")
                if project.complete_wbs_code:
                    label = f"{project.complete_wbs_code} {label}"
                project.display_name = label

    @api.depends("account_id.parent_id")
    def _compute_child(self):
        for project in self:
            project.project_child_complete_ids = self.search(
                [("account_id.parent_id", "=", project.account_id.id)]
            )

    @api.depends("project_child_complete_ids")
    def _compute_has_child(self):
        for project in self:
            project.has_project_child_complete_ids = bool(project.project_child_complete_ids)

    def _resolve_analytic_account_id_from_context(self):
        context = self.env.context or {}
        if isinstance(context.get("default_parent_id"), int):
            return context["default_parent_id"]
        return None

    def prepare_analytics_vals(self, vals):
        project_plan, _other_plans = self.env["account.analytic.plan"]._get_all_plans()
        return {
            "name": vals.get("name", _("Unknown Analytic Account")),
            "company_id": vals.get("company_id", self.env.user.company_id.id),
            "partner_id": vals.get("partner_id"),
            "plan_id": vals.get("plan_id", project_plan.id),
            "active": True,
        }

    @api.model
    def _map_legacy_vals(self, vals):
        vals = dict(vals)
        if "analytic_account_id" in vals and "account_id" not in vals:
            vals["account_id"] = vals.pop("analytic_account_id")
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._map_legacy_vals(vals) for vals in vals_list]
        projects = super().create(vals_list)
        for project, vals in zip(projects, vals_list):
            if not project.account_id and not project.is_template:
                project._create_analytic_account()
            if not project.account_id:
                continue
            account_vals = {}
            parent_id = vals.get("parent_id") or project._resolve_analytic_account_id_from_context()
            if parent_id:
                parent = self.env["account.analytic.account"].browse(parent_id)
                account_vals["parent_id"] = parent.id
                account_vals["account_class"] = vals.get("account_class", parent.account_class)
            elif vals.get("account_class"):
                account_vals["account_class"] = vals["account_class"]
            if vals.get("code"):
                account_vals["code"] = vals["code"]
            if account_vals:
                project.account_id.write(account_vals)
        return projects

    def write(self, vals):
        vals = self._map_legacy_vals(vals)
        res = super().write(vals)
        if "parent_id" in vals:
            self.env["account.analytic.account"].browse(
                self.account_id.get_child_accounts().keys()
            )._recompute_wbs_fields()
        if vals.get("active"):
            for project in self.filtered(lambda item: item.account_id and not item.account_id.active):
                project.account_id.active = True
        return res

    def action_open_child_view(self, act_window):
        self.ensure_one()
        res = self.env["ir.actions.act_window"]._for_xml_id(act_window)
        child_project_ids = self.search([("account_id.parent_id", "=", self.account_id.id)]).ids
        res["context"] = {
            "default_parent_id": self.account_id.id or False,
            "default_partner_id": self.partner_id.id or False,
            "default_user_id": self.user_id.id or False,
        }
        res.update(
            {
                "display_name": self.name,
                "domain": [("id", "in", child_project_ids)],
                "nodestroy": False,
            }
        )
        return res

    def action_open_child_tree_view(self):
        self.ensure_one()
        return self.action_open_child_view("project_wbs.open_view_project_wbs")

    def action_open_child_kanban_view(self):
        self.ensure_one()
        return self.action_open_child_view("project_wbs.open_view_wbs_kanban")

    def action_open_parent_tree_view(self):
        self.ensure_one()
        res = self.env["ir.actions.act_window"]._for_xml_id("project_wbs.open_view_project_wbs")
        parent_projects = self.search([("account_id", "=", self.account_id.parent_id.id)])
        if parent_projects:
            res.update({"domain": [("id", "in", parent_projects.ids)], "nodestroy": False})
        res["display_name"] = self.name
        return res

    def action_open_parent_kanban_view(self):
        self.ensure_one()
        res = self.env["ir.actions.act_window"]._for_xml_id("project_wbs.open_view_wbs_kanban")
        parent_projects = self.search([("account_id", "=", self.account_id.parent_id.id)])
        if parent_projects:
            res.update({"domain": [("id", "in", parent_projects.ids)], "nodestroy": False})
        return res

    @api.onchange("parent_id")
    def on_change_parent(self):
        if self.account_id:
            self.account_id.parent_id = self.parent_id
            self.account_id._onchange_parent_id()

    def action_open_view_project_form(self):
        self.ensure_one()
        return {
            "name": _("Details"),
            "view_mode": "form,list,kanban",
            "res_model": "project.project",
            "view_id": False,
            "type": "ir.actions.act_window",
            "target": "current",
            "res_id": self.id,
            "context": self.env.context,
        }
