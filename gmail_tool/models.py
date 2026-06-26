from pydantic import BaseModel


class Attachment(BaseModel):
    filename: str
    mime_type: str
    gmail_size_bytes: int


class EmailListItem(BaseModel):
    message_id: str
    thread_id: str
    sent_at: str
    from_address: str
    to: list[str]
    cc: list[str]
    subject: str
    labels: list[str]
    gmail_size_bytes: int


class Email(BaseModel):
    message_id: str
    thread_id: str
    sent_at: str
    from_address: str
    to: list[str]
    cc: list[str]
    bcc: bool
    subject: str
    body: str
    labels: list[str]
    gmail_size_bytes: int
    attachments: list[Attachment]


class SenderGroup(BaseModel):
    address: str
    display_name: str | None
    email_count: int
    total_gmail_size_bytes: int
    oldest_sent_at: str
    newest_sent_at: str
    email_ids: list[str]


class RecipientGroup(BaseModel):
    address: str
    display_name: str | None
    email_count: int
    total_gmail_size_bytes: int
    oldest_sent_at: str
    newest_sent_at: str
    email_ids: list[str]


