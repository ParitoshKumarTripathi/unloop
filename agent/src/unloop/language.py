"""Per-session spoken-language profiles, shared by every support domain."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .config import AppConfig
from .resolution.hypotheses import Hypothesis


@dataclass(frozen=True)
class LanguageProfile:
    id: str
    label: str
    stt_language: str
    rime_language: str
    rime_model: str | None
    rime_speaker: str | None
    response_instruction: str
    opening_line: str | None = None


LANGUAGES: dict[str, LanguageProfile] = {
    "english": LanguageProfile(
        id="english",
        label="English",
        stt_language="en",
        rime_language="eng",
        rime_model=None,
        rime_speaker=None,
        response_instruction="Speak only in natural, concise English.",
    ),
    "hindi": LanguageProfile(
        id="hindi",
        label="हिन्दी",
        stt_language="hi",
        rime_language="hin",
        rime_model="coda",
        # Verified in Rime's live coda/hin catalog on 2026-09-08.
        rime_speaker="taru",
        response_instruction=(
            "ग्राहक से स्वाभाविक, सरल हिन्दी और देवनागरी लिपि में बात करें। "
            "तकनीकी नामों को जरूरत पड़ने पर आम बोलचाल की हिन्दी में समझाएँ।"
        ),
        opening_line=("नमस्ते, मैं आपकी सहायता करूँगा। कृपया बताइए कि अभी क्या समस्या आ रही है?"),
    ),
}


def get_language(language_id: str | None) -> LanguageProfile:
    """Return a supported language, falling back safely to English."""
    return LANGUAGES.get((language_id or "english").strip().lower(), LANGUAGES["english"])


def configure_session_language(config: AppConfig, profile: LanguageProfile) -> AppConfig:
    """Apply a language profile without mutating process-wide configuration."""
    return replace(
        config,
        stt=replace(config.stt, language=profile.stt_language),
        rime=replace(
            config.rime,
            model=profile.rime_model or config.rime.model,
            language=profile.rime_language,
            speaker=profile.rime_speaker or config.rime.speaker,
        ),
    )


def available_languages() -> list[dict[str, str]]:
    return [
        {
            "id": profile.id,
            "label": profile.label,
            "stt_language": profile.stt_language,
            "rime_language": profile.rime_language,
        }
        for profile in LANGUAGES.values()
    ]


_MULTILINGUAL_ASSERTIONS: dict[str, str] = {
    "CARD_BLOCKED": r"(?:card|कार्ड)[^.?!]{0,35}(?:block|blocked|freeze|frozen|ब्लॉक|बंद)",
    "ONLINE_TXN_DISABLED": r"(?:online|ऑनलाइन)[^.?!]{0,30}(?:payment|transaction|पेमेंट|भुगतान)[^.?!]{0,25}(?:off|disabled|बंद)",
    "MOBILE_NOT_REGISTERED": r"(?:mobile|phone|number|मोबाइल|फ़ोन|नंबर)[^.?!]{0,30}(?:register|verify|update|रजिस्टर|वेरिफ|पुराना)",
    "OTP_NOT_GENERATED": r"(?:OTP|ओटीपी)[^.?!]{0,30}(?:generate|create|बना|जनरेट)",
    "OTP_DELIVERY_FAILED": r"(?:OTP|SMS|message|ओटीपी|मैसेज)[^.?!]{0,35}(?:deliver|reach|receive|पहुंच|मिल)",
    "SMS_PROVIDER_INCIDENT": r"(?:SMS|message|एसएमएस)[^.?!]{0,30}(?:provider|service|network|प्रोवाइडर|सेवा)[^.?!]{0,20}(?:down|outage|issue|बंद|दिक्कत)",
    "REFUND_ALREADY_RECEIVED": r"(?:refund|रिफंड)[^.?!]{0,35}(?:receive|received|credit|aa chuka|mil chuka|मिल चुका|आ चुका|क्रेडिट)",
    "REFUND_NOT_SUBMITTED": r"(?:merchant|seller|मर्चेंट|विक्रेता)[^.?!]{0,35}(?:refund|रिफंड)[^.?!]{0,25}(?:submit|start|भेज|शुरू)",
    "PAYMENT_RAIL_DELAY": r"(?:refund|रिफंड)[^.?!]{0,30}(?:rail|bank|gateway|बैंक|गेटवे)[^.?!]{0,25}(?:delay|stuck|pending|देरी|अटका)",
    "REFUND_RETURNED": r"(?:refund|रिफंड)[^.?!]{0,35}(?:return|wapas|वापस)[^.?!]{0,25}(?:merchant|seller|मर्चेंट|विक्रेता)",
    "RESTAURANT_HAS_BOOKING": r"(?:restaurant|रेस्टोरेंट)[^.?!]{0,35}(?:has|found|see|paas|mil|के पास|मिल)[^.?!]{0,20}(?:booking|reservation|बुकिंग|रिजर्वेशन)",
    "PLATFORM_CONFIRMATION_INVALID": r"(?:confirmation|booking|reservation|कन्फर्मेशन|बुकिंग)[^.?!]{0,30}(?:invalid|wrong|galat|अमान्य|गलत)",
    "RESERVATION_SYNC_FAILURE": r"(?:reservation|booking|रिजर्वेशन|बुकिंग)[^.?!]{0,35}(?:sync|सिंक)[^.?!]{0,20}(?:fail|missing|नहीं हुआ|फेल)",
    "RESERVATION_DETAILS_MISMATCH": r"(?:reservation|booking|रिजर्वेशन|बुकिंग)[^.?!]{0,35}(?:detail|date|time|name|डिटेल|तारीख|समय)[^.?!]{0,20}(?:mismatch|different|wrong|अलग|गलत)",
    "APPOINTMENT_UNCHANGED": r"(?:appointment|अपॉइंटमेंट)[^.?!]{0,35}(?:unchanged|same|confirmed|नहीं बदला|वैसा ही|कन्फर्म)",
    "MERCHANT_CANCELLED_APPOINTMENT": r"(?:salon|merchant|सैलून|मर्चेंट)[^.?!]{0,35}(?:cancel|रद्द|कैंसल)[^.?!]{0,20}(?:appointment|अपॉइंटमेंट)",
    "APPOINTMENT_CHANGED_IN_ERROR": r"(?:appointment|अपॉइंटमेंट)[^.?!]{0,35}(?:change|move|cancel|बदल|रद्द)[^.?!]{0,20}(?:mistake|error|गलती)",
    "APPOINTMENT_SYNC_FAILURE": r"(?:appointment|अपॉइंटमेंट)[^.?!]{0,35}(?:sync|सिंक)[^.?!]{0,20}(?:fail|missing|नहीं हुआ|फेल)",
    "HOTEL_HAS_BOOKING": r"(?:hotel|होटल)[^.?!]{0,35}(?:has|found|see|paas|mil|के पास|मिल)[^.?!]{0,20}(?:booking|reservation|बुकिंग|रिजर्वेशन)",
    "PLATFORM_BOOKING_INVALID": r"(?:platform|confirmation|booking|प्लेटफॉर्म|कन्फर्मेशन|बुकिंग)[^.?!]{0,35}(?:invalid|wrong|galat|अमान्य|गलत)",
    "HOTEL_SYNC_FAILURE": r"(?:booking|reservation|बुकिंग|रिजर्वेशन)[^.?!]{0,35}(?:sync|सिंक)[^.?!]{0,20}(?:fail|missing|नहीं हुआ|फेल)",
    "HOTEL_DETAILS_CONFLICT": r"(?:hotel|booking|होटल|बुकिंग)[^.?!]{0,35}(?:detail|date|room|guest|डिटेल|तारीख|कमरा|मेहमान)[^.?!]{0,20}(?:conflict|mismatch|different|wrong|अलग|गलत)",
}

_MULTILINGUAL_NEGATION = re.compile(
    r"\b(?:nahi|nahin|na|galat\s+nahi)\b|(?:नहीं|नही|ना|गलत नहीं)", re.IGNORECASE
)


def augment_hypotheses_for_language(
    hypotheses: list[Hypothesis], profile: LanguageProfile
) -> list[Hypothesis]:
    """Teach the deterministic speech guard Hindi and common code-switched assertion forms."""
    if profile.id == "english":
        return hypotheses
    for hypothesis in hypotheses:
        pattern = _MULTILINGUAL_ASSERTIONS.get(hypothesis.id)
        if pattern:
            hypothesis.assertion_patterns.append(re.compile(pattern, re.IGNORECASE))
        hypothesis.negation_cues.append(_MULTILINGUAL_NEGATION)
    return hypotheses
