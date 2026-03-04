import os
import re
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

# In-memory conversation state per group or DM.
# key: group_id or phone number
# value: {"topic", "questions": [str,str,str], "q_index": int, "answers": [], "recipient"}
conversation_state: dict = {}


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
    if not resp.ok:
        log.error("Send mislukt HTTP %s: %s", resp.status_code, resp.text[:500])
    resp.raise_for_status()
    log.info("Bericht verstuurd naar %s", recipient)


def generate_questions(topic: str) -> list[str]:
    """Generate exactly 3 questions for the given topic. Returns a list of 3 strings."""
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
    text = response.content[0].text
    return _parse_numbered_list(text)


def _parse_numbered_list(text: str) -> list[str]:
    """Split a numbered list ('1. ...\\n\\n2. ...\\n\\n3. ...') into individual strings."""
    # Split on blank lines, then strip leading "N. "
    parts = re.split(r"\n\s*\n", text.strip())
    questions = []
    for part in parts:
        cleaned = re.sub(r"^\d+\.\s*", "", part.strip())
        if cleaned:
            questions.append(cleaned)
    return questions[:3]


def generate_summary(topic: str, questions: list[str], answers: list[str]) -> str:
    """Generate a short session summary based on topic, questions and answers."""
    qa_block = "\n\n".join(
        f"Vraag: {q}\nAntwoord: {a}"
        for q, a in zip(questions, answers)
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Een kleine groep professionals bereidt zich voor op hun wekelijkse gesprek "
                    f"over: \"{topic}\".\n\n"
                    f"Ze hebben deze vragen beantwoord:\n\n{qa_block}\n\n"
                    f"Schrijf een korte samenvatting (3-5 zinnen) in het Nederlands die:\n"
                    f"- De kern van het onderwerp scherp stelt\n"
                    f"- De persoonlijke relevantie benoemt\n"
                    f"- Aangeeft waar het gesprek naartoe kan gaan\n\n"
                    f"Begin direct met de samenvatting, geen inleiding of afsluiting."
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


def get_group_recipient(raw_group_id: str) -> str:
    """Resolve the exact recipient string for a group by querying the groups list."""
    try:
        resp = requests.get(
            f"{SIGNAL_API_URL}/v1/groups/{PHONE_NUMBER}",
            timeout=30,
        )
        if resp.ok:
            groups = resp.json() or []
            for group in groups:
                api_id = group.get("id", "")
                try:
                    # API stores group IDs as base64url(groupId_string_bytes) — double-encoded.
                    api_id_inner = api_id.removeprefix("group.")
                    decoded_str = base64.urlsafe_b64decode(api_id_inner + "==").decode("ascii")
                    if decoded_str.rstrip("=") == raw_group_id.rstrip("="):
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

    uri = GROUP_INVITE_URI
    if uri.startswith("https://signal.group/#"):
        uri = "signal-group://#" + uri.split("#", 1)[1]

    log.info("Groepslink join proberen met URI: %s...", uri[:40])

    for endpoint in [
        f"{SIGNAL_API_URL}/v1/groups/join/{PHONE_NUMBER}",
        f"{SIGNAL_API_URL}/v1/groups/{PHONE_NUMBER}/join",
    ]:
        try:
            resp = requests.post(endpoint, json={"uri": uri}, timeout=30)
            log.info("Join via %s: HTTP %s", endpoint, resp.status_code)
            if resp.ok:
                return
        except requests.RequestException as e:
            log.warning("Fout bij %s: %s", endpoint, e)


def process_envelope(envelope: dict):
    data_message = envelope.get("dataMessage") or {}
    if not data_message:
        return

    message_text = (data_message.get("message") or "").strip()
    if not message_text:
        return

    sender = envelope.get("sourceNumber") or envelope.get("source", "")

    # Ignore messages sent by the bot itself
    if sender == PHONE_NUMBER:
        return

    group_info = data_message.get("groupInfo") or {}
    group_id = group_info.get("groupId", "")

    if group_id:
        recipient = get_group_recipient(group_id)
    elif sender:
        recipient = sender
        log.info("Direct bericht ontvangen van %s", sender)
    else:
        log.warning("Geen groep of afzender gevonden, wordt genegeerd.")
        return

    state_key = group_id or sender
    topic = extract_topic(message_text)

    # --- /topic command: start a new conversation flow ---
    if topic:
        log.info("Topic ontvangen: %s", topic)
        try:
            questions = generate_questions(topic)
        except Exception as e:
            log.error("Fout bij genereren vragen: %s", e)
            return

        if len(questions) < 3:
            log.error("Verwacht 3 vragen, kreeg %d — tekst: %s", len(questions), questions)
            return

        conversation_state[state_key] = {
            "topic": topic,
            "questions": questions,
            "q_index": 0,
            "answers": [],
            "recipient": recipient,
        }

        try:
            send_message(f"📋 *{topic}*\n\n1. {questions[0]}", recipient)
        except Exception as e:
            log.error("Fout bij versturen vraag 1: %s", e)
        return

    # --- Any other command: ignore ---
    if message_text.startswith("/"):
        return

    # --- Regular message: treat as answer to current question ---
    state = conversation_state.get(state_key)
    if not state:
        return

    state["answers"].append(message_text)
    state["q_index"] += 1
    recipient = state["recipient"]

    if state["q_index"] < len(state["questions"]):
        # Send the next question
        q_num = state["q_index"] + 1
        q_text = state["questions"][state["q_index"]]
        log.info("Versturen vraag %d", q_num)
        try:
            send_message(f"{q_num}. {q_text}", recipient)
        except Exception as e:
            log.error("Fout bij versturen vraag %d: %s", q_num, e)
    else:
        # All 3 questions answered — generate and send session summary
        log.info("Alle vragen beantwoord, samenvatting genereren voor topic: %s", state["topic"])
        try:
            summary = generate_summary(state["topic"], state["questions"], state["answers"])
            send_message(f"📝 *Samenvatting voor de sessie: {state['topic']}*\n\n{summary}", recipient)
        except Exception as e:
            log.error("Fout bij versturen samenvatting: %s", e)
        del conversation_state[state_key]


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
