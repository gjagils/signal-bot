import os
import time
import logging
import requests
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SIGNAL_API_URL = os.environ["SIGNAL_API_URL"]
PHONE_NUMBER = os.environ["PHONE_NUMBER"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def receive_messages():
    resp = requests.get(
        f"{SIGNAL_API_URL}/v1/receive/{PHONE_NUMBER}",
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() or []


def send_message(message: str, recipient: str):
    payload = {
        "message": message,
        "number": PHONE_NUMBER,
        "recipients": [recipient],
    }
    resp = requests.post(
        f"{SIGNAL_API_URL}/v2/send",
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    log.info("Bericht verstuurd naar %s", recipient)


def generate_questions(topic: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Je helpt een kleine groep professionals om hun wekelijkse gesprekken "
                    f"dieper te maken.\n\n"
                    f"Iemand wil het volgende onderwerp inbrengen: \"{topic}\"\n\n"
                    f"Genereer precies 3 verdiepende vragen in het Nederlands. "
                    f"De vragen moeten helpen om te begrijpen:\n"
                    f"- Waarom wil de persoon dit onderwerp bespreken?\n"
                    f"- Wat maakt dit onderwerp persoonlijk relevant of interessant voor hen?\n"
                    f"- Welke diepere inzichten, spanning of overtuiging zit er achter dit onderwerp?\n\n"
                    f"De vragen gaan over de mens die het onderwerp inbrengt, niet over het onderwerp zelf. "
                    f"Formuleer ze uitnodigend, open en niet confronterend. "
                    f"Begin direct met de drie genummerde vragen, geen inleiding."
                ),
            }
        ],
    )
    return response.content[0].text


def extract_topic(message_text: str) -> str | None:
    text = message_text.strip()
    if text.lower().startswith("/topic "):
        topic = text[7:].strip()
        return topic if topic else None
    return None


def accept_pending_invitations():
    try:
        resp = requests.get(
            f"{SIGNAL_API_URL}/v1/groups/{PHONE_NUMBER}",
            timeout=30,
        )
        resp.raise_for_status()
        groups = resp.json() or []
        log.info("Groepscheck: %d groepen gevonden", len(groups))
        for group in groups:
            group_id = group.get("id", "")
            group_name = group.get("name", group_id)
            if not group_id:
                continue

            log.info(
                "Groep '%s': members=%s pendingMembers=%s",
                group_name,
                group.get("members"),
                group.get("pendingMembers"),
            )

            # Try to accept for every group — if already a member the API returns
            # a non-2xx response (harmless). If there's a pending invitation it accepts.
            # This handles UUIDs and phone numbers alike without needing to match.
            try:
                accept_resp = requests.put(
                    f"{SIGNAL_API_URL}/v1/groups/{PHONE_NUMBER}/{group_id}",
                    json={},
                    timeout=30,
                )
                if accept_resp.ok:
                    log.info("Groep '%s' bijgewerkt/uitnodiging geaccepteerd", group_name)
                else:
                    log.info(
                        "Groep '%s' PUT: HTTP %s %s",
                        group_name,
                        accept_resp.status_code,
                        accept_resp.text[:200],
                    )
            except requests.RequestException as e:
                log.warning("Fout bij groep '%s': %s", group_name, e)
    except requests.RequestException as e:
        log.warning("Fout bij ophalen groepen: %s", e)
    except Exception as e:
        log.error("Onverwachte fout bij uitnodigingscheck: %s", e)


def process_envelope(envelope: dict):
    data_message = envelope.get("dataMessage", {})
    if not data_message:
        return

    message_text = data_message.get("message", "") or ""
    topic = extract_topic(message_text)
    if not topic:
        return

    group_info = data_message.get("groupInfo", {})
    group_id = group_info.get("groupId", "")
    sender = envelope.get("sourceNumber") or envelope.get("source", "")

    if group_id:
        recipient = f"group.{group_id}"
    elif sender:
        recipient = sender
        log.info("Direct bericht ontvangen van %s", sender)
    else:
        log.warning("Geen groep of afzender gevonden, wordt genegeerd.")
        return

    log.info("Topic ontvangen: %s", topic)

    try:
        questions = generate_questions(topic)
    except Exception as e:
        log.error("Fout bij genereren vragen: %s", e)
        return

    response_text = f"📋 *{topic}*\n\n{questions}"

    try:
        send_message(response_text, recipient)
    except Exception as e:
        log.error("Fout bij versturen bericht: %s", e)


def main():
    log.info("Signal bot gestart. Luistert op %s", PHONE_NUMBER)
    last_invitation_check = 0
    while True:
        now = time.time()
        if now - last_invitation_check >= 60:
            accept_pending_invitations()
            last_invitation_check = now

        try:
            messages = receive_messages()
            for msg in messages:
                envelope = msg.get("envelope", {})
                if envelope:
                    process_envelope(envelope)
        except requests.RequestException as e:
            log.warning("Verbindingsfout met signal-cli-rest-api: %s", e)
        except Exception as e:
            log.error("Onverwachte fout: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
