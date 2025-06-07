import os
import re
import smtplib
import requests
import mailersend
from mailersend import emails
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()               


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ICONS_DIR = os.path.join(BASE_DIR, 'static', 'images', 'icons')


app = FastAPI()

# app.mount("/static", StaticFiles(directory=BASE_DIR + "/static"), name="static")
# app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")

templates = Jinja2Templates(directory=BASE_DIR + "/templates")
def hyphen_filter(s: str) -> str:
    return re.sub(r"\s+", "-", s)

# Register the filter on the Jinja2 environment:
templates.env.filters["hyphen"] = hyphen_filter


@app.get("/")
def index(request: Request):
    return "Welcome to the Email Service API! Use the /test endpoint to test email templates."


@app.post("/test")
async def test(request: Request):
    data = await request.json() 
    return email_constructor_html(request, data)


@app.post("/send")
async def send(request: Request):
    email_status = ''
    data = await request.json() 
    email_content = email_constructor(request, data)
    if data.get('type') == "self":
        
        SMTP = {
            "host":     os.getenv("SMTP_HOST"),
            "port":     int(os.getenv("SMTP_PORT", 587)),
            "username": os.getenv("SMTP_USER_INFO"),
            "password": os.getenv("SMTP_PASS_INFO"),
            "sender":   os.getenv("SMTP_SENDER_INFO")
        }

        email_status = send_html_email(
            subject=data.get("subject"),
            to_email=data.get("mail_to_email"),
            sender=SMTP["sender"],
            html=email_content,
            SMTP=SMTP
        )

    if data.get('type') == "mailersend":
        email_status = mailerSend_html(data, email_content)

    return email_status


def email_constructor(request: Request, content: dict):
    full_content = {
        "request": request,
        "BASE_DIR": BASE_DIR,
        **content
    }

    jinja2_env = templates.env
    myTemplate = jinja2_env.get_template(content.get("template"))
    return myTemplate.render(full_content)

def email_constructor_html(request: Request, content: dict):
    full_content = {
        "request": request,
        "BASE_DIR": BASE_DIR,
        **content
    }

    return templates.TemplateResponse(content.get("template"), full_content)

def send_html_email(subject: str, to_email: str, sender: str, html, SMTP: dict):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    # plain-text fallback
    msg.set_content("This is an HTML email. Please view in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    # Send via SMTP with STARTTLS
    with smtplib.SMTP(SMTP["host"], SMTP["port"]) as server:
        server.set_debuglevel(1)
        server.starttls()
        server.login(SMTP["username"], SMTP["password"])
        server.send_message(msg)
        print(f"Sent to {to_email}")

        return JSONResponse(
            {"message": f"Email sent to {to_email}"},
            status_code=200
        )

def mailerSend_html(data: dict, html: str):
    """
    Sends an HTML email via MailerSend’s API using requests.
    - First, it checks status codes / response text to avoid JSONDecodeError.
    - Raises an exception if MailerSend returns 4xx/5xx.
    - Returns a dict (parsed JSON) on success, or an empty dict if no JSON is returned.
    """
    # 1) Load your MailerSend API key from the environment
    API_KEY = os.getenv("MAILERSEND_API_KEY_info")
    if not API_KEY:
        raise RuntimeError("Please set MAILERSEND_API_KEY in your environment.")

    # 2) Build the plain-text body (ensure you fix any f-string quoting here)
    #    Using single-quoted f-strings so inner double-quotes don’t break syntax:
    text_body = (
        f'Hi { data.get("mail_to") },\n\n'
        f'Thanks for signing up! Please confirm your email:\n{ data.get("btn_0_href") }\n\n'
        'If you did not register, please ignore this.'
    )

    # 3) Ensure "subject" is non-empty
    subject_line = data.get("subject")
    if not subject_line:
        subject_line = "Welcome to MyApp!"  # or raise an error

    # 4) Build the JSON payload exactly as MailerSend expects
    payload = {
        "from": {
            "email": os.getenv("MAILERSEND_EMAIL"), 
            "name": os.getenv("MY_EMAIL") 
        },
        "to": [
            {
                "email": data.get("mail_to_email"),
                "name": data.get("mail_to")
            }
        ],
        "subject": subject_line,
        "html": html,
        "text": text_body
    }

    # 5) Send the POST request
    url = os.getenv("MAILERSEND_API_URL") 
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    resp = requests.post(url, json=payload, headers=headers)

    # 6) If MailerSend returns a 4xx/5xx, immediately raise an HTTPError
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        # Print status and body for debugging (the user can view these logs)
        print(f"MailerSend API returned an error: {resp.status_code}")
        print("Response body:", repr(resp.text))
        # Re-raise so your FastAPI endpoint can catch & convert to HTTPException
        raise

    # 7) At this point, resp.status_code is 2xx.
    #    MailerSend usually returns JSON, but just in case it's 204 or empty, guard it:
    if resp.status_code in (200, 201, 202):  # MailerSend returns 200/202 on success
        # Some APIs return 202 Accepted with an empty body; handle JSONDecodeError
        try:
            result = resp.json()
        except ValueError:
            # No JSON to parse; return an empty dict
            result = {}
    else:
        # Unexpected success code (e.g. 204), return empty dict
        result = {}

    print("Email sent! MailerSend response:", result)
    return result
    