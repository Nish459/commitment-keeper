"""A made-up week of mail for the demo. Synthetic people and addresses only."""

from datetime import date, timedelta

from kept.domain.models import Mail

SAMPLE_OWNER = "you@kept.example"


def _mail(
    today: date,
    days_ago: int,
    sender: tuple[str, str],
    to: tuple[str, str],
    subject: str,
    body: str,
) -> Mail:
    return Mail(
        subject=subject,
        sender_name=sender[0],
        sender_address=sender[1],
        to_names=(to[0],),
        to_addresses=(to[1],),
        sent=today - timedelta(days=days_ago),
        body=body,
        from_me=sender[1] == SAMPLE_OWNER,
    )


def sample_mails(today: date) -> list[Mail]:
    me = ("You", SAMPLE_OWNER)
    return [
        _mail(
            today,
            1,
            ("Priya Raman", "priya@acme.example"),
            me,
            "Re: Partnership terms",
            "Thanks for the call yesterday. I'll send over the signed NDA by end of next week so "
            "legal can start. Could you share the draft terms before then?",
        ),
        _mail(
            today,
            2,
            me,
            ("Aisha Khan", "aisha@northwind.example"),
            "Project timeline",
            "Hi Aisha, good to catch up. I'll send you the revised project timeline by next "
            "Monday, with the new milestones marked.",
        ),
        _mail(
            today,
            1,
            ("Tom Becker", "tom@northwind.example"),
            me,
            "Demo room booking",
            "Quick note on the demo. I'll book the large meeting room and confirm with "
            "you by tomorrow.",
        ),
        _mail(
            today,
            3,
            me,
            ("Lee Chen", "lee@partner.example"),
            "Intro to security",
            "Hi Lee, yes, happy to help with the security questionnaire. I'll introduce you to "
            "our security lead by next Wednesday.",
        ),
        _mail(
            today,
            4,
            ("Sam Ortiz", "sam@vendor.example"),
            me,
            "Renewal quote",
            "We value your business. We'll send the renewal quote by end of the month.",
        ),
        _mail(
            today,
            4,
            ("Product Weekly", "newsletter@productweekly.example"),
            me,
            "This week in product",
            "Ten roadmap mistakes to avoid. Read more on our site.",
        ),
        _mail(
            today,
            5,
            ("Jordan Lee", "jordan@acme.example"),
            me,
            "Lunch?",
            "Are you free for lunch on Thursday? There's a new place near the office.",
        ),
    ]
