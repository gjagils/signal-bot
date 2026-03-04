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
GROUP_INVITE_URI = os.environ.get("GROUP_INVITE_URI", "")

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
                    f"Genereer precies 3 vragen in het Nederlands, in deze volgorde:\n\n"
                    f"1. Een verhelderende vraag — vraag door op het onderwerp zelf. "
                    f"Wat bedoelt de persoon precies? Welke context of definitie zit er achter? "
                    f"Maak het concreet zonder aannames te doen.\n\n"
                    f"2. Een verdiepende vraag — over de persoon, niet het onderwerp. "
                    f"Waarom brengt hij of zij dit nu in? Wat maakt het persoonlijk relevant, "
                    f"urgent of beladen? Raak aan wat er écht speelt.\n\n"
                    f"3. Een uitkomstgerichte vraag — wat zou de persoon willen hebben aan "
                    f"het einde van het gesprek? Welk inzicht, besluit, opluchting of "
                    f"verschuiving zou helpen?\n\n"
                    f"Varieer de formulering — vermijd standaardopeningen als 'Wat bedoel je met' "
                    f"of 'Wat wil je bereiken'. Wees specifiek op het onderwerp. "
                    f"Uitnodigend, open, niet confronterend. "
                    f"Begin direct met de drie genummerde vragen, geen inleiding of afsluiting."
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


def setup_profile():
    try:
        resp = requests.put(
            f"{SIGNAL_API_URL}/v1/profiles/{PHONE_NUMBER}",
            json={"name": "Signal Bot"},
            timeout=30,
        )
        if resp.ok:
            log.info("Profiel ingesteld")
        else:
            log.warning("Kon profiel niet instellen (HTTP %s): %s", resp.status_code, resp.text[:200])
    except requests.RequestException as e:
        log.warning("Fout bij instellen profiel: %s", e)


def join_via_link():
    """Join the group via an invite link (signal-group:// URI).
    More reliable than accepting a direct invitation for signal-cli V2 groups.
    """
    if not GROUP_INVITE_URI:
        return

    # Convert https://signal.group/#... to signal-group://#...
    uri = GROUP_INVITE_URI
    if uri.startswith("https://signal.group/#"):
        uri = "signal-group://#" + uri.split("#", 1)[1]

    try:
        resp = requests.post(
            f"{SIGNAL_API_URL}/v1/groups/join/{PHONE_NUMBER}",
            json={"uri": uri},
            timeout=30,
        )
        if resp.ok:
            log.info("Groep succesvol gejoined via link")
        else:
            log.info("Join via link: HTTP %s %s", resp.status_code, resp.text[:200])
    except requests.RequestException as e:
        log.warning("Fout bij joinen via groepslink: %s", e)


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
    setup_profile()
    join_via_link()

    while True:
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
