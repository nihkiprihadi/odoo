import logging

from odoo.api import SUPERUSER_ID, Environment
from odoo.sql_db import BaseCursor

logger = logging.getLogger(__name__)


def _next_legacy_wbs_code(env, analytic_account):
    sequence_code = env["ir.sequence"].next_by_code("project.wbs.analytic.code")
    return sequence_code or f"LEGACY-WBS-{analytic_account.id}"


def pre_init_hook(env_or_cr):
    if isinstance(env_or_cr, BaseCursor):
        env = Environment(env_or_cr, SUPERUSER_ID, {})
    else:
        env = env_or_cr
    # avoid crashing installation because of having same complete_wbs_code
    for aa in (
        env["account.analytic.account"]
        .with_context(active_test=False)
        .search([("code", "=", False)])
    ):
        aa._write({"code": _next_legacy_wbs_code(env, aa)})
    logger.info("Assigning default code to existing analytic accounts")

    projects = (
        env["project.project"]
        .with_context(active_test=False)
        .search([("account_id", "=", False), ("allow_timesheets", "=", True)])
    )
    projects._create_analytic_account()
    projects.filtered(lambda p: not p.active).mapped("account_id").write(
        {"active": False}
    )
