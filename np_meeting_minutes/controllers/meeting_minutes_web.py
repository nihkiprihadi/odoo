# -*- coding: utf-8 -*-

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request


class MeetingMinutesWebController(http.Controller):
    @http.route("/np_meeting_minutes/<int:meeting_id>/print_web", type="http", auth="user", website=False)
    def print_web(self, meeting_id, **kwargs):
        meeting = request.env["np.meeting.minutes"].browse(meeting_id)
        if not meeting.exists():
            raise MissingError("Meeting not found.")
        meeting.check_access_rights("read")
        meeting.check_access_rule("read")
        return request.render(
            "np_meeting_minutes.report_np_meeting_minutes_web_document",
            {"meeting": meeting},
        )
