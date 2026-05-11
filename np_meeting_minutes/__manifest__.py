# -*- coding: utf-8 -*-
{
    "name": "PTN Notulen Meeting",
    "version": "19.0.1.0.0",
    "summary": "Notulen meeting dengan histori perubahan per item pembahasan",
    "description": """
        Module untuk mencatat notulen meeting, item pembahasan,
        PIC, deadline, status, dan histori perubahan.
    """,
    "category": "Productivity",
    "author": "Nihki Prihadi",
    "license": "LGPL-3",
    "depends": [
        "base",
        "hr",
        "mail",
    ],
    "data": [
        "security/meeting_minutes_security.xml",
        "security/ir.model.access.csv",
        "security/meeting_minutes_rules.xml",
        "data/meeting_minutes_sequence.xml",
        "views/meeting_minutes_views.xml",
        "report/meeting_minutes_report.xml",
    ],
    "images": [
        "static/description/banner.png",
    ],
    "installable": True,
    "application": True,
}
