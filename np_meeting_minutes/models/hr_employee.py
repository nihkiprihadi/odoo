# -*- coding: utf-8 -*-

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    initial_name = fields.Char(string="Initial Name")

    # Allow internal users to resolve employee records in notulen pickers
    # without granting full HR Officer access.
    version_id = fields.Many2one(
        "hr.version",
        string="Version",
        readonly=True,
        ondelete="cascade",
        groups="base.group_user",
    )
