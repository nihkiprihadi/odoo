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
            {"meeting": meeting, "is_public": False},
        )

    @http.route(
        "/np_meeting_minutes/reviewer/<int:reviewer_id>/open/<string:token>",
        type="http",
        auth="public",
        website=False,
    )
    def reviewer_public_open(self, reviewer_id, token, **kwargs):
        reviewer = request.env["np.meeting.minutes.reviewer"].sudo().browse(reviewer_id)
        if not reviewer.exists():
            raise MissingError("Reviewer not found.")
        if not reviewer.access_token or reviewer.access_token != token:
            raise AccessError("Invalid reviewer token.")
        return request.render(
            "np_meeting_minutes.report_np_meeting_minutes_web_document",
            {
                "meeting": reviewer.meeting_id.sudo(),
                "is_public": True,
                "reviewer": reviewer,
            },
        )

    @http.route(
        "/np_meeting_minutes/reviewer/<int:reviewer_id>/review/<string:token>",
        type="http",
        auth="public",
        methods=["POST"],
        website=False,
    )
    def reviewer_public_mark_reviewed(self, reviewer_id, token, **post):
        reviewer = request.env["np.meeting.minutes.reviewer"].sudo().browse(reviewer_id)
        if not reviewer.exists():
            raise MissingError("Reviewer not found.")
        if not reviewer.access_token or reviewer.access_token != token:
            raise AccessError("Invalid reviewer token.")
        reviewer.action_mark_reviewed_public(post.get("review_note"))
        return request.redirect(
            "/np_meeting_minutes/reviewer/%s/open/%s?reviewed=1" % (reviewer.id, reviewer.access_token)
        )
