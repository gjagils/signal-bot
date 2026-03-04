import os
import time
import base64
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
    log.info("Versturen naar recipient: %r", recipient)
    resp = requests.post(
        f"{SIGNAL_API_URL}/v2/send",
        json=payload,
        timeout=30,
    )
    if not resp.ok:
        log.error("Send mislukt HTTP %s: %s", resp.status_code, resp.text[:500])
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


def log_group_endpoints():
    """Fetch swagger and log available group-related endpoints."""
    for path in ["/v1/api-docs", "/swagger.yaml", "/api/swagger.json"]:
        try:
            resp = requests.get(f"{SIGNAL_API_URL}{path}", timeout=10)
            if resp.ok:
                try:
                    docs = resp.json()
                    paths = [p for p in docs.get("paths", {}) if "group" in p.lower()]
                    log.info("Group endpoints in swagger: %s", paths)
                except Exception:
                    log.info("Swagger op %s (niet JSON): %s", path, resp.text[:300])
                return
        except requests.RequestException:
            pass
    log.info("Geen swagger gevonden")


def get_group_recipient(raw_group_id: str) -> str:
    """Resolve the exact recipient string for a group by querying the groups list.

    The groupId in received messages may use a different encoding than what
    /v2/send expects. Fetching the API's group list gives us the canonical ID.
    Falls back to a best-effort encoding conversion if the lookup fails.
    """
    try:
        resp = requests.get(
            f"{SIGNAL_API_URL}/v1/groups/{PHONE_NUMBER}",
            timeout=30,
        )
        if resp.ok:
            groups = resp.json() or []
            log.info("Groepen opgehaald: %d gevonden", len(groups))
            for group in groups:
                api_id = group.get("id", "")
                log.info("  Groep: id=%r name=%r", api_id, group.get("name", ""))
                # The API id is typically "group.<base64url-no-padding>"
                # The received groupId is standard base64 with padding.
                # Normalise both to raw bytes for comparison.
                try:
                    # The API id is base64url(groupId_string_bytes), i.e. double-encoded.
                    # Decode the API id back to the original groupId string and compare.
                    api_id_inner = api_id.removeprefix("group.")
                    decoded_str = base64.urlsafe_b64decode(api_id_inner + "==").decode("ascii")
                    if decoded_str.rstrip("=") == raw_group_id.rstrip("="):
                        log.info("Match gevonden: %r", api_id)
                        return api_id
                except Exception:
                    if api_id.endswith(raw_group_id.rstrip("=")):
                        return api_id
        else:
            log.warning("Groepen ophalen mislukt HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("Fout bij ophalen groepen: %s", e)

    # Fallback: best-effort conversion
    try:
        raw = base64.b64decode(raw_group_id + "==")
        safe = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        return f"group.{safe}"
    except Exception:
        return f"group.{raw_group_id.rstrip('=')}"


def join_via_link():
    """Join the group via an invite link (signal-group:// URI)."""
    if not GROUP_INVITE_URI:
        return

    # Convert https://signal.group/#... to signal-group://#...
    uri = GROUP_INVITE_URI
    if uri.startswith("https://signal.group/#"):
        uri = "signal-group://#" + uri.split("#", 1)[1]

    log.info("Groepslink join proberen met URI: %s...", uri[:40])

    # Try both known endpoint variants
    for endpoint in [
        f"{SIGNAL_API_URL}/v1/groups/join/{PHONE_NUMBER}",
        f"{SIGNAL_API_URL}/v1/groups/{PHONE_NUMBER}/join",
    ]:
        try:
            resp = requests.post(endpoint, json={"uri": uri}, timeout=30)
            log.info("Join via %s: HTTP %s %s", endpoint, resp.status_code, resp.text[:200])
            if resp.ok:
                return
        except requests.RequestException as e:
            log.warning("Fout bij %s: %s", endpoint, e)


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
        recipient = get_group_recipient(group_id)
        log.info("Groep ID uit bericht: %r → recipient: %r", group_id, recipient)
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
    log_group_endpoints()
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
