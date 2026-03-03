# CLAUDE.md — signal-bot

## Wat doet dit project

Een Signal bot die luistert naar `/topic <onderwerp>` in een groepschat.
Bij detectie genereert de bot 3 verdiepende vragen via Claude API (Nederlandstalig)
over de motivatie van de persoon die het onderwerp inbrengt, niet over het onderwerp zelf.

## Architectuur

Twee Docker containers in één Portainer stack:

- `signal-cli-rest-api` — bbernhard/signal-cli-rest-api, handelt Signal protocol af
- `signal-bot` — onze Python service (ghcr.io/gjagils/signal-bot:latest)

CI/CD pipeline: Claude Code → GitHub (push/merge) → GitHub Actions → ghcr.io → Tailscale → Portainer API → Synology Docker update

## Omgevingsvariabelen (stack.env in Portainer)

| Variabele          | Beschrijving                            |
|--------------------|-----------------------------------------|
| `PHONE_NUMBER`     | Het bottelefoonummer (bijv. +31...)     |
| `ANTHROPIC_API_KEY`| Claude API key                          |
| `POLL_INTERVAL`    | Polling interval in seconden (default 5)|

`SIGNAL_API_URL` wordt gezet via docker-compose environment (intern netwerk).

## GitHub Secrets

| Secret                | Herbruikbaar?       |
|-----------------------|---------------------|
| `TAILSCALE_AUTHKEY`   | Ja                  |
| `PORTAINER_API_TOKEN` | Ja                  |
| `PORTAINER_URL`       | Ja                  |
| `PORTAINER_STACK_ID`  | Nee, uniek per project |

## Setup checklist nieuw project

- [ ] `signal-cli-rest-api` registreren met het bottelefoonummer (zie Setup Signal)
- [ ] Portainer stack aanmaken met `docker-compose.yml`
- [ ] `stack.env` invullen in Portainer
- [ ] GitHub repo aanmaken en secrets instellen
- [ ] Eerste push naar main (triggert image build)
- [ ] GitHub Packages visibility instellen (public of gjagils toevoegen)

## Setup Signal (eenmalig)

Na het starten van de stack, registreer het nummer via de signal-cli-rest-api container:

```bash
# Vraag verificatiecode aan via SMS
curl -X POST "http://localhost:8080/v1/register/<PHONE_NUMBER>"

# Verifieer met de ontvangen code
curl -X POST "http://localhost:8080/v1/register/<PHONE_NUMBER>/verify/<CODE>"
```

## Commit conventie

- `feat:` — nieuwe feature
- `fix:` — bugfix
- `docs:` — documentatie
- `chore:` — onderhoud
- `refactor:` — refactoring
