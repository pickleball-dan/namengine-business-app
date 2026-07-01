import json
import os
import random
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from flask import Flask, abort, redirect, render_template, request, url_for
from markupsafe import Markup

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    import gspread
except ImportError:
    gspread = None

if load_dotenv:
    load_dotenv(Path(__file__).with_name('.env'))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'namengine-dev-secret')
SHORTLIST_STORE = {}
MAX_SHORTLISTS = 200
MAX_REFINEMENT_ROUNDS = 2
SHARE_STORE_PATH = Path(os.getenv('SHARE_STORE_PATH', Path(__file__).with_name('share_store.json')))
FEEDBACK_STORE_PATH = Path(os.getenv('FEEDBACK_STORE_PATH', Path(__file__).with_name('feedback_store.json')))
DOMAIN_CACHE_PATH = Path(os.getenv('DOMAIN_CACHE_PATH', Path(__file__).with_name('domain_cache.json')))
DOMAIN_CACHE_TTL_SECONDS = int(os.getenv('DOMAIN_CACHE_TTL_SECONDS', str(6 * 60 * 60)))
DOMAIN_UNKNOWN_CACHE_TTL_SECONDS = int(os.getenv('DOMAIN_UNKNOWN_CACHE_TTL_SECONDS', str(15 * 60)))
FEEDBACK_RATE_LIMIT = {}
PLATFORM_HOME_URL = os.getenv('NAMENGINE_HOME_URL', 'https://namegine-main-1.onrender.com/')
STATIC_DIR = Path(__file__).with_name('static')


def write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    temp_path.replace(path)


def inline_svg(filename):
    svg_path = (STATIC_DIR / filename).resolve()
    static_root = STATIC_DIR.resolve()
    try:
        svg_path.relative_to(static_root)
    except ValueError:
        return ''
    if svg_path.suffix.lower() != '.svg':
        return ''
    try:
        return Markup(svg_path.read_text(encoding='utf-8'))
    except OSError:
        return ''

REACTION_OPTIONS = [
    {
        'value': 'love',
        'label': 'LOVE',
        'hover_text': "Exactly the feeling I'm looking for.",
        'image': 'images/reactions/love.jpg',
    },
    {
        'value': 'too_trendy',
        'label': 'TRENDY',
        'hover_text': 'Feels a bit too fashionable right now.',
        'image': 'images/reactions/trendy.jpg',
    },
    {
        'value': 'too_soft',
        'label': 'SOFT',
        'hover_text': "A little gentler than I'd like.",
        'image': 'images/reactions/soft.jpg',
    },
    {
        'value': 'maybe',
        'label': 'MAYBE',
        'hover_text': 'Save it for now and compare later.',
        'image': 'images/reactions/maybe.jpg',
    },
    {
        'value': 'too_common',
        'label': 'COMMON',
        'hover_text': "I'd like something more distinctive.",
        'image': 'images/reactions/common.jpg',
    },
    {
        'value': 'hard_to_pronounce',
        'label': 'CONFUSING',
        'hover_text': 'Too difficult to say or understand.',
        'image': 'images/reactions/confusing.jpg',
    },
    {
        'value': 'no',
        'label': 'NO',
        'hover_text': 'Not the direction I want.',
        'image': 'images/reactions/no.jpg',
    },
]

REACTION_LABELS = {item['value']: item['label'] for item in REACTION_OPTIONS}
REACTION_IMAGES = {item['value']: item['image'] for item in REACTION_OPTIONS}
PRIMARY_REACTION_VALUES = {'love', 'maybe', 'no'}
PRIMARY_REACTION_OPTIONS = [item for item in REACTION_OPTIONS if item['value'] in PRIMARY_REACTION_VALUES]


@app.context_processor
def inject_reaction_labels():
    return {
        'reaction_labels': REACTION_LABELS,
        'reaction_images': REACTION_IMAGES,
        'discovery_style_options': DISCOVERY_STYLE_OPTIONS,
        'cultural_feel_options': CULTURAL_FEEL_OPTIONS,
        'industry_options': INDUSTRY_OPTIONS,
        'market_position_options': MARKET_POSITION_OPTIONS,
        'feedback_enabled': feedback_enabled(),
        'live_brief_enabled': live_brief_enabled(),
        'platform_home_url': PLATFORM_HOME_URL,
        'inline_svg': inline_svg,
    }

ORIGINAL_TUNE_OPTIONS = [
    {'label': 'Softer', 'value': 'softer'},
    {'label': 'More classic', 'value': 'more_classic'},
    {'label': 'More modern', 'value': 'more_modern'},
    {'label': 'More distinctive', 'value': 'more_distinctive'},
]
ORIGINAL_TUNE_LABELS = {item['value']: item['label'] for item in ORIGINAL_TUNE_OPTIONS}

DISCOVERY_STYLE_OPTIONS = [
    'Classic favorites',
    'Balanced mix',
    'Unexpected finds',
    'Completely original',
]

CULTURAL_FEEL_OPTIONS = [
    'Descriptive',
    'Suggestive',
    'Abstract',
    'Founder-style',
    'Compound word',
    'Real word',
    'Coined word',
    'Local / geographic',
    'Premium / editorial',
    'Warm and human',
]

INDUSTRY_OPTIONS = [
    'Technology / software',
    'Healthcare / wellness',
    'Food / hospitality',
    'Finance / professional services',
    'Education / coaching',
    'Construction / home services',
    'Staffing / recruiting',
    'Retail / consumer goods',
    'Creative / media',
    'Nonprofit / community',
    'Other / not sure',
]

MARKET_POSITION_OPTIONS = [
    'Fast and dependable',
    'Human and caring',
    'Polished and premium',
    'Local and trusted',
    'Bold and modern',
    'Operational and no-nonsense',
    'Creative and memorable',
    'Established and professional',
]

CULTURAL_SOUND_PARTS = {
    'african': (
        ['Ama', 'Kofi', 'Nia', 'Zola', 'Ayo', 'Imani', 'Sana', 'Tali'],
        ['na', 'mi', 'ko', 'la', 'zi', 'ari', 'aya'],
        ['a', 'i', 'o', 'en', 'ara', 'ani'],
    ),
    'american': (
        ['Har', 'Em', 'Aver', 'Cal', 'Hud', 'Lau', 'Madd', 'Wes'],
        ['per', 'son', 'ley', 'den', 'lin', 'ryn', 'ton'],
        ['a', 'en', 'er', 'ley', 'lyn', 'on'],
    ),
    'arabic': (
        ['Ami', 'Lay', 'Noor', 'Sami', 'Zai', 'Rami', 'Mira', 'Hadi'],
        ['ra', 'la', 'din', 'yan', 'mir', 'iya', 'ima'],
        ['a', 'ah', 'ia', 'in', 'an', 'ir'],
    ),
    'british': (
        ['Al', 'Bea', 'Ed', 'Flor', 'Har', 'Ivy', 'Theo', 'Wil'],
        ['len', 'ton', 'rose', 'win', 'lie', 'ford', 'ora'],
        ['a', 'ie', 'en', 'or', 'ton', 'ley'],
    ),
    'chinese': (
        ['Ai', 'Bao', 'Jia', 'Lin', 'Mei', 'Ren', 'Tao', 'Xia'],
        ['li', 'mei', 'an', 'wei', 'yun', 'lan', 'hao'],
        ['a', 'an', 'in', 'ing', 'ai', 'ao'],
    ),
    'french': (
        ['Ana', 'Beau', 'Cel', 'El', 'Lou', 'Ma', 'Noe', 'Viv'],
        ['lie', 'ette', 'ien', 'elle', 'oise', 'ren', 'ina'],
        ['a', 'e', 'el', 'elle', 'ien', 'ine'],
    ),
    'german': (
        ['Ad', 'An', 'Brun', 'Clau', 'Els', 'Gre', 'Mat', 'Wil'],
        ['el', 'win', 'rich', 'lena', 'hart', 'ina', 'mar'],
        ['a', 'en', 'el', 'er', 'ina', 'rich'],
    ),
    'greek': (
        ['Ana', 'Cal', 'Dio', 'Eli', 'Ione', 'Leo', 'Theo', 'Zoe'],
        ['dra', 'lia', 'niko', 'ora', 'thea', 'ene', 'ion'],
        ['a', 'ia', 'on', 'os', 'is', 'ene'],
    ),
    'hebrew': (
        ['Ari', 'Eli', 'Levi', 'Miri', 'Noa', 'Rafi', 'Tali', 'Zev'],
        ['el', 'ora', 'av', 'iah', 'omi', 'elle', 'ani'],
        ['a', 'ah', 'el', 'en', 'ia', 'iel'],
    ),
    'indian': (
        ['Avi', 'Devi', 'Ila', 'Kavi', 'Mira', 'Navi', 'Ravi', 'Tara'],
        ['na', 'vi', 'sha', 'ani', 'indra', 'aya', 'ika'],
        ['a', 'an', 'ani', 'ika', 'iya', 'vi'],
    ),
    'international / blended': (
        ['Ari', 'El', 'Kai', 'Leo', 'Mira', 'Nia', 'Noa', 'Rumi', 'Tavi', 'Zara'],
        ['la', 'mi', 'ra', 'vi', 'en', 'ora', 'ari', 'lia'],
        ['a', 'en', 'ia', 'el', 'i', 'o'],
    ),
    'irish': (
        ['Ail', 'Bri', 'Cai', 'Ena', 'Finn', 'Kee', 'Mae', 'Rory'],
        ['dan', 'ley', 'ra', 'nan', 'ven', 'lin', 'ora'],
        ['a', 'an', 'en', 'ey', 'in', 'ra'],
    ),
    'italian': (
        ['Al', 'Gia', 'Leo', 'Luca', 'Mira', 'Nico', 'Rafa', 'Sera'],
        ['lia', 'rio', 'etta', 'vanni', 'ella', 'ina', 'ora'],
        ['a', 'ia', 'io', 'ina', 'ella', 'o'],
    ),
    'japanese': (
        ['Aki', 'Hana', 'Kai', 'Mio', 'Ren', 'Sora', 'Yuki', 'Toma'],
        ['ko', 'mi', 'ra', 'shi', 'na', 'to', 'ari'],
        ['a', 'i', 'o', 'ko', 'mi', 'ren'],
    ),
    'korean': (
        ['Ara', 'Dae', 'Eun', 'Hana', 'Jae', 'Mina', 'Seo', 'Yuna'],
        ['bin', 'ha', 'jin', 'mi', 'ri', 'seo', 'won'],
        ['a', 'in', 'un', 'mi', 'seo', 'won'],
    ),
    'latin american': (
        ['Ana', 'Bel', 'Cami', 'Die', 'Elia', 'Luna', 'Mate', 'Sofi'],
        ['lia', 'rio', 'ela', 'ito', 'ana', 'mar', 'isa'],
        ['a', 'ia', 'io', 'el', 'ita', 'o'],
    ),
    'nordic': (
        ['Astr', 'Eli', 'Fre', 'Inga', 'Kai', 'Lina', 'Soren', 'Tor'],
        ['rid', 'len', 'ja', 'sten', 'liv', 'rik', 'una'],
        ['a', 'en', 'ia', 'in', 'or', 'rid'],
    ),
    'persian': (
        ['Ara', 'Cyr', 'Dari', 'Lale', 'Mina', 'Roya', 'Sami', 'Zara'],
        ['min', 'yan', 'ra', 'vash', 'naz', 'ian', 'iya'],
        ['a', 'an', 'ia', 'in', 'iya', 'ra'],
    ),
    'scottish': (
        ['Ail', 'Bla', 'Cal', 'Ewan', 'Fia', 'Greer', 'Lach', 'Mais'],
        ['len', 'air', 'nan', 'rie', 'don', 'ina', 'ven'],
        ['a', 'an', 'en', 'ie', 'air', 'on'],
    ),
    'spanish': (
        ['Al', 'Caro', 'Die', 'Elena', 'Ines', 'Lola', 'Mate', 'Rafa'],
        ['lia', 'rio', 'ana', 'ela', 'ito', 'isa', 'ora'],
        ['a', 'ia', 'io', 'el', 'ita', 'o'],
    ),
}

FALLBACK_NAMES = [
    {
        "name": "Northline",
        "pronunciation": "NORTH-line",
        "origin": "English compound",
        "style": "clear and directional",
        "meaning": "a guiding line or route north",
        "why": "A steady, practical name with a sense of direction and trust.",
    },
    {
        "name": "Blueforge",
        "pronunciation": "BLOO-forj",
        "origin": "English compound",
        "style": "confident and industrious",
        "meaning": "building something strong with calm authority",
        "why": "It feels capable, durable, and useful without sounding cold.",
    },
    {
        "name": "Signal & Co.",
        "pronunciation": "SIG-nul and koh",
        "origin": "English word name",
        "style": "sharp and strategic",
        "meaning": "a clear sign or message",
        "why": "A concise brand name for work that helps people notice what matters.",
    },
    {
        "name": "Cedar House",
        "pronunciation": "SEE-der house",
        "origin": "Nature compound",
        "style": "warm and established",
        "meaning": "strength, shelter, and natural durability",
        "why": "It sounds grounded and human, especially for a studio, practice, or local business.",
    },
    {
        "name": "Asterly",
        "pronunciation": "AS-ter-lee",
        "origin": "coined name from aster / star imagery",
        "style": "modern and polished",
        "meaning": "star-like direction and clarity",
        "why": "Distinctive enough to own, but still easy to say and remember.",
    },
    {
        "name": "Foundry Lane",
        "pronunciation": "FOWN-dree layn",
        "origin": "English compound",
        "style": "craft-driven and credible",
        "meaning": "a place where ideas are shaped into real things",
        "why": "It gives a business maker energy without feeling gimmicky.",
    },
    {
        "name": "Verda",
        "pronunciation": "VAIR-duh",
        "origin": "coined name with green / true associations",
        "style": "simple and distinctive",
        "meaning": "freshness, truth, and growth",
        "why": "Short, brandable, and flexible across categories.",
    },
    {
        "name": "Keystone Works",
        "pronunciation": "KEE-stohn wurks",
        "origin": "English compound",
        "style": "trustworthy and substantial",
        "meaning": "the central piece that holds a system together",
        "why": "A strong fit for a service business that wants reliability front and center.",
    },
]

BRAND_RESEARCH_GUIDANCE = """Research-informed business naming guidance:
- Balance processing fluency with distinctiveness. Easy-to-say and easy-to-spell names feel more familiar and trustworthy, but overly generic names are harder to remember and harder to protect.
- Prefer names with a clear strategic job: describe the category, suggest a benefit, evoke a feeling, or create a memorable invented asset.
- Trademark strength matters as a product signal: suggestive, arbitrary, and fanciful names are generally stronger than merely descriptive or generic names. Do not imply legal clearance.
- Sound symbolism can support positioning. Crisp consonants can feel sharp, fast, technical, or energetic; softer consonants and open vowels can feel warm, human, calm, or premium.
- Brand names should be short enough to remember, distinct enough to search, and natural enough to say in a sales call, invoice, podcast ad, or referral.
- Avoid names that are too close to obvious competitors, too stuffed with category keywords, too trendy-SaaS, or too clever to understand.
- For local/service businesses, clarity and trust can matter more than extreme originality. For apps/products/startups, ownability and search distinction matter more.
- Treat these as ranking signals, not rigid rules. A slightly less fluent name can win if it creates a stronger strategic position.
"""

PROMPT_TEMPLATE = """You are NamEngine Business's hidden naming strategist.
Your job is to turn fuzzy human taste into a sharp, premium list.
Return exactly 8 business names as valid HTML-free JSON with this schema:
{{
  \"names\": [
    {{
      \"name\": \"...\",
      \"pronunciation\": \"...\",
      \"origin\": \"...\",
      \"style\": \"...\",
      \"meaning\": \"...\",
      \"emotional_opener\": \"2-5 words that capture the first impression\",
      \"why\": \"1-2 sentence explanation\"
    }}
  ]
}}

Core standards:
- Avoid filler and generic listicle energy.
- Suggestions must feel thoughtful, tasteful, strategically aware, and usable in real market life.
- Mix safer and slightly more distinctive options unless the user's taste clearly wants one side only.
- No repeated names.
- Keep explanations concise but specific.
- Add an emotional_opener that feels premium, human, and specific. Avoid cliches and avoid repeating the name.
- Include a short, readable phonetic pronunciation for each name.
- Favor names with staying power over names that merely sound current.
- Pay attention to pronounceability, spelling friction, memorability, trademark strength posture, searchability, brand signal, market fit, and emotional tone.
- If the taste notes suggest market compromise or mixed tastes, reflect that in the list balance.
- Use the research guidance below quietly when ranking names. Do not mention research unless it directly helps explain fit.
- Business guardrails: for local/service businesses, avoid overly abstract names; for apps/products/startups, avoid bland descriptive names; for nonprofits, protect warmth and clarity; for studios, allow more editorial/personality-led names.

Decision policy:
- Treat HARD CONSTRAINTS as non-negotiable.
- Treat SOFT PREFERENCES as directional, not absolute.
- Treat VETOES as names or qualities to move away from.
- Treat EMOTIONAL GOALS as part of evaluation, not decorative language.
- Prefer names that still feel good after repeated use in real business contexts.
- Explanations should say why the name fits this taste specifically, not why it is generally nice.

Here is the structured taste:
{details}
"""

ORIGINAL_PROMPT_TEMPLATE = """You are NamEngine Business's original-name strategist.
Create new business-name candidates that feel premium, pronounceable, and emotionally specific.

Return exactly 5 original names as valid HTML-free JSON with this schema:
{{
  \"names\": [
    {{
      \"name\": \"...\",
      \"pronunciation\": \"...\",
      \"style\": \"...\",
      \"structure\": \"...\",
      \"emotional_opener\": \"2-5 words that capture the first impression\",
      \"why\": \"...\",
      \"fit_note\": \"...\",
      \"originality_note\": \"...\"
    }}
  ]
}}

Core standards:
- Create names, do not simply return obvious category phrases or existing famous brand patterns.
- Avoid established famous brands, obvious competitor echoes, and generic keyword stuffing; every result should feel newly coined, suggestive, or meaningfully transformed.
- Do not use names that already strongly evoke major companies, products, platforms, or common startup cliches.
- Discovery style controls how conservative or adventurous the names should feel; even Classic favorites should avoid generic category phrases.
- Names should still feel usable for a real business in real market use.
- Use plain ASCII spellings only; do not use accent marks or special characters.
- Avoid fantasy, product-code, app-name, and random-syllable energy unless the user explicitly asks for boldness.
- Original business names should sound like something a founder could say in a pitch, domain search, invoice, and referral. Avoid fantasy-character endings and empty app-name shapes unless explicitly requested.
- Add an emotional_opener that explains the first impression in a short, human phrase.
- Favor clean spoken shape, good mouthfeel, and social usability.
- Use naming direction as a creative cue for strategy, imagery, rhythm, and sound, not as a claim of legal availability.
- If a starting letter is supplied, honor it unless it would badly damage the name.
- Respect previous names and do not repeat or make near duplicates.
- The originality note should be honest: say low-match / inspired shape / not guaranteed globally unique.
- Use the research guidance below quietly when ranking names. Do not mention research unless it directly helps explain fit.

Here is the structured original-name taste:
{details}
"""

DEFAULT_FORM_DATA = {
    'pet_type': '',
    'business_description': '',
    'target_audience': '',
    'industry': '',
    'avoid_feel': '',
    'discovery_style': '',
    'style': '',
    'vibe': '',
    'market_position': '',
    'cultural_context': '',
    'timeless_vs_distinctive': '',
    'familiarity_preference': '',
    'pronunciation_importance': '',
    'partner_alignment': '',
    'notes': '',
}

ORIGINAL_FORM_DATA = {
    'pet_type': '',
    'business_description': '',
    'target_audience': '',
    'industry': '',
    'avoid_feel': '',
    'discovery_style': '',
    'style': '',
    'vibe': '',
    'market_position': '',
    'familiarity_preference': '',
    'pronunciation_importance': '',
    'starting_letter': '',
    'length_preference': '',
    'cultural_context': '',
    'notes': '',
}

QUESTION_LABELS = {
    'pet_type': 'Project type',
    'business_description': 'What the business does',
    'target_audience': 'Who it serves',
    'industry': 'Industry',
    'avoid_feel': 'Avoid',
    'discovery_style': 'Discovery style',
    'style': 'Taste leaning',
    'vibe': 'Immediate signal',
    'market_position': 'Market feel',
    'cultural_context': 'Name inspiration',
    'timeless_vs_distinctive': 'Timeless vs distinctive',
    'familiarity_preference': 'Familiarity preference',
    'pronunciation_importance': 'Easy to say',
    'partner_alignment': 'Taste differences',
    'notes': 'Business notes',
}


def normalized_form_data(source, defaults=None):
    defaults = defaults or DEFAULT_FORM_DATA
    return {key: (source.get(key, '') if source else '') for key in defaults}


def infer_dimensions(form_data):
    return {
        'business_context': form_data.get('business_description') or 'not specified',
        'audience_context': form_data.get('target_audience') or 'not specified',
        'industry_context': form_data.get('industry') or 'not specified',
        'discovery_style': form_data.get('discovery_style') or 'open',
        'style_vector': form_data.get('style') or 'balanced',
        'tone_vector': form_data.get('vibe') or 'open-ended',
        'market_position': form_data.get('market_position') or 'open-ended',
        'distinctiveness_tolerance': form_data.get('timeless_vs_distinctive') or 'balanced',
        'familiarity_preference': form_data.get('familiarity_preference') or 'open',
        'pronunciation_friction_tolerance': form_data.get('pronunciation_importance') or 'moderate',
        'relationship_context': form_data.get('partner_alignment') or 'not specified',
    }


def round_word(number):
    words = {1: 'one', 2: 'two', 3: 'three'}
    return words.get(number, str(number))


def human_join(items):
    items = [item for item in items if item]
    if len(items) <= 1:
        return ''.join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def make_round_label(round_number):
    return f"Round {round_word(round_number)}"


def make_refinement_label(round_number):
    return f"Round-{round_word(round_number)} refinement"


def build_details(form_data, refinement_note=''):
    dimensions = infer_dimensions(form_data)

    business_context = []
    hard_constraints = []
    soft_preferences = []
    vetoes = []
    emotional_goals = []
    compromise_notes = []

    if form_data.get('pet_type'):
        hard_constraints.append(f"Project type: {form_data['pet_type']}")
    if form_data.get('business_description'):
        business_context.append(f"What the business does: {form_data['business_description']}")
    if form_data.get('target_audience'):
        business_context.append(f"Who it serves: {form_data['target_audience']}")
    if form_data.get('industry'):
        business_context.append(f"Industry/category: {form_data['industry']}")
    if form_data.get('pronunciation_importance'):
        hard_constraints.append(f"Easy-to-say requirement: {form_data['pronunciation_importance']}")

    if form_data.get('style'):
        soft_preferences.append(f"Style leaning: {form_data['style']}")
    if form_data.get('discovery_style'):
        soft_preferences.append(f"Discovery style / search range: {form_data['discovery_style']}")
    if form_data.get('cultural_context'):
        soft_preferences.append(f"Name inspiration to lean toward: {form_data['cultural_context']}")
    if form_data.get('timeless_vs_distinctive'):
        soft_preferences.append(f"Distinctiveness balance: {form_data['timeless_vs_distinctive']}")
    if form_data.get('familiarity_preference'):
        soft_preferences.append(f"Familiarity preference: {form_data['familiarity_preference']}")
    if form_data.get('market_position'):
        soft_preferences.append(f"Market feel: {form_data['market_position']}")

    if form_data.get('vibe'):
        emotional_goals.append(f"Immediate signal to capture: {form_data['vibe']}")
    if form_data.get('notes'):
        business_context.append(f"Additional business context: {form_data['notes']}")

    if form_data.get('avoid_feel'):
        vetoes.append(f"Names should avoid feeling like: {form_data['avoid_feel']}")

    if form_data.get('partner_alignment'):
        compromise_notes.append(f"Taste notes or tensions: {form_data['partner_alignment']}")
    if refinement_note:
        compromise_notes.append(refinement_note)

    hidden_interpretation = [
        f"Discovery style: {dimensions['discovery_style']}",
        f"Style vector: {dimensions['style_vector']}",
        f"Tone vector: {dimensions['tone_vector']}",
        f"Market position: {dimensions['market_position']}",
        f"Distinctiveness tolerance: {dimensions['distinctiveness_tolerance']}",
        f"Familiarity preference: {dimensions['familiarity_preference']}",
        f"Pronunciation friction tolerance: {dimensions['pronunciation_friction_tolerance']}",
        f"Decision context: {dimensions['relationship_context']}",
    ]

    return "\n".join([
        "RESEARCH-INFORMED NAMING SIGNALS:",
        BRAND_RESEARCH_GUIDANCE,
        business_research_guidance(form_data),
        "",
        "BUSINESS CONTEXT / POSITIONING:",
        *(f"- {item}" for item in (business_context or ["No business context supplied."])),
        "",
        "HARD CONSTRAINTS:",
        *(f"- {item}" for item in (hard_constraints or ["No hard constraints supplied."])),
        "",
        "SOFT PREFERENCES:",
        *(f"- {item}" for item in (soft_preferences or ["No soft preferences supplied."])),
        "",
        "VETOES / MOVE-AWAY SIGNALS:",
        *(f"- {item}" for item in (vetoes or ["No explicit vetoes supplied."])),
        "",
        "EMOTIONAL GOALS:",
        *(f"- {item}" for item in (emotional_goals or ["No emotional goals supplied."])),
        "",
        "COMPROMISE / DECISION DYNAMICS:",
        *(f"- {item}" for item in (compromise_notes or ["No compromise notes supplied."])),
        "",
        "HIDDEN INTERPRETATION:",
        *(f"- {item}" for item in hidden_interpretation),
    ])


def project_type_category(form_data):
    project_type = ' '.join([
        form_data.get('pet_type') or '',
        form_data.get('industry') or '',
        form_data.get('business_description') or '',
    ]).lower()
    if any(token in project_type for token in ['app', 'software', 'platform', 'tool', 'saas']):
        return 'app_product'
    if any(token in project_type for token in ['product', 'consumer product', 'goods']):
        return 'product'
    if any(token in project_type for token in ['studio', 'agency', 'creative', 'consultancy', 'consulting']):
        return 'studio'
    if any(token in project_type for token in ['nonprofit', 'foundation', 'community']):
        return 'nonprofit'
    if any(token in project_type for token in ['newsletter', 'media', 'content', 'publication']):
        return 'media'
    if any(token in project_type for token in ['staffing', 'recruiting', 'talent', 'local', 'service', 'shop', 'practice']):
        return 'local_service'
    if any(token in project_type for token in ['business', 'company', 'startup']):
        return 'business'
    return 'general_business'


BUSINESS_PROFILES = {
    'app_product': {
        'label': 'App / product',
        'sayability_weight': 0.9,
        'confusion_weight': 0.9,
        'guidance': 'Prioritize distinctiveness, searchability, clean spelling, and a name that can stretch into a product ecosystem.',
    },
    'product': {
        'label': 'Product',
        'sayability_weight': 0.85,
        'confusion_weight': 0.8,
        'guidance': 'Prioritize shelf memory, sensory sound, and a short name that can be repeated naturally.',
    },
    'studio': {
        'label': 'Studio / agency',
        'sayability_weight': 0.75,
        'confusion_weight': 0.75,
        'guidance': 'Allow more editorial personality, but keep credibility and referral clarity high.',
    },
    'nonprofit': {
        'label': 'Nonprofit',
        'sayability_weight': 0.8,
        'confusion_weight': 0.6,
        'guidance': 'Prioritize trust, clarity, warmth, and mission resonance over clever abstraction.',
    },
    'media': {
        'label': 'Newsletter / media',
        'sayability_weight': 0.75,
        'confusion_weight': 0.8,
        'guidance': 'Prioritize memorability, point of view, and a name that works as a title people can share.',
    },
    'local_service': {
        'label': 'Local / service business',
        'sayability_weight': 0.85,
        'confusion_weight': 0.55,
        'guidance': 'Prioritize immediate clarity, trust, and word-of-mouth ease. Avoid names that are too abstract for local referrals.',
    },
    'business': {
        'label': 'Business',
        'sayability_weight': 0.8,
        'confusion_weight': 0.75,
        'guidance': 'Balance strategic clarity, memorability, and long-term ownability.',
    },
    'general_business': {
        'label': 'Business',
        'sayability_weight': 0.8,
        'confusion_weight': 0.7,
        'guidance': 'Balance fluency, distinctiveness, emotional fit, and trademark-strength posture.',
    },
}


def business_profile(form_data):
    return BUSINESS_PROFILES.get(project_type_category(form_data), BUSINESS_PROFILES['general_business'])


def business_research_guidance(form_data):
    profile = business_profile(form_data)
    return f"{profile['label']} weighting: {profile['guidance']}"


WEAK_OR_CONFUSING_BRAND_TERMS = {
    'best', 'top', 'pro', 'prime', 'solutions', 'services', 'group', 'global', 'labs',
    'ai', 'tech', 'digital', 'innovations', 'systems', 'consulting'
}


LEGAL_OR_CULTURAL_RISK_NAMES = {
    'apple', 'stripe', 'amazon', 'meta', 'google', 'tesla', 'openai', 'notion',
    'slack', 'zoom', 'figma', 'nike', 'uber', 'airbnb'
}

FANTASY_OR_APP_ORIGINAL_MARKERS = [
    'zy', 'q', 'xq', 'qz', 'xar', 'vyr', 'thos', 'lix', 'lyft', 'ify', 'io',
]


def brand_confusion_penalty(name, form_data):
    cleaned = re.sub(r'[^a-z]', '', (name or '').lower())
    if not cleaned:
        return 0

    penalty = 0
    if cleaned in LEGAL_OR_CULTURAL_RISK_NAMES:
        penalty -= 30
    if cleaned in WEAK_OR_CONFUSING_BRAND_TERMS:
        penalty -= 10
    if any(cleaned.endswith(term) for term in ['solutions', 'services', 'systems', 'global', 'digital']):
        penalty -= 8
    if any(token in cleaned for token in ['best', 'cheap', 'ez', 'quickfix']):
        penalty -= 10
    return round(penalty * business_profile(form_data)['confusion_weight'])


def sayability_score(name, form_data):
    cleaned = re.sub(r'[^a-z]', '', (name or '').lower())
    if not cleaned:
        return 0
    syllables = syllable_count(cleaned)
    score = 0
    if syllables in {2, 3}:
        score += 10
    elif syllables == 1:
        score += 4
    elif syllables > 4:
        score -= 12
    if 5 <= len(cleaned) <= 10:
        score += 8
    elif len(cleaned) > 14:
        score -= 12
    if re.search(r'[ktpdbgvz]|ch', cleaned):
        score += 4
    if cleaned.endswith(('a', 'o', 'er', 'ly', 'ra', 'on', 'us', 'io')):
        score += 3
    if re.search(r'(.)\1{2,}', cleaned) or re.search(r'[^aeiouy]{4,}', cleaned):
        score -= 10
    if cleaned.count('x') + cleaned.count('q') + cleaned.count('z') > 2:
        score -= 8
    score += brand_confusion_penalty(cleaned, form_data)
    return round(score * business_profile(form_data)['sayability_weight'])


def business_style_score(name, form_data):
    cleaned = re.sub(r'[^a-z]', '', (name or '').lower())
    category = project_type_category(form_data)
    if not cleaned:
        return 0
    score = 0
    if category == 'local_service':
        if len(cleaned) <= 12:
            score += 4
        if any(term in cleaned for term in ['house', 'works', 'care', 'home', 'north', 'stone', 'field']):
            score += 5
        if len(cleaned) <= 5 and syllable_count(cleaned) <= 1:
            score -= 4
    elif category == 'app_product':
        if 5 <= len(cleaned) <= 9:
            score += 5
        if any(marker in cleaned for marker in ['labs', 'ai', 'io', 'ify']):
            score -= 6
    elif category == 'studio':
        if any(term in cleaned for term in ['studio', 'house', 'lane', 'works', 'atelier']):
            score += 4
        if len(cleaned) > 13:
            score -= 4
    elif category == 'nonprofit':
        if any(term in cleaned for term in ['bridge', 'heart', 'open', 'root', 'rise', 'common']):
            score += 5
        if any(term in cleaned for term in ['hack', 'disrupt', 'scale']):
            score -= 8
    elif category == 'media':
        if any(term in cleaned for term in ['letter', 'brief', 'daily', 'signal', 'dispatch', 'note']):
            score += 5
    return score


def business_curated_penalty(name, form_data):
    cleaned = re.sub(r'[^a-z]', '', (name or '').lower())
    category = project_type_category(form_data)
    if not cleaned:
        return 0
    penalty = 0
    if cleaned in LEGAL_OR_CULTURAL_RISK_NAMES:
        penalty -= 30
    if category == 'local_service' and len(cleaned) > 15:
        penalty -= 10
    if category in {'app_product', 'product'} and cleaned in WEAK_OR_CONFUSING_BRAND_TERMS:
        penalty -= 12
    if any(marker in cleaned for marker in ['xq', 'qz', 'zzr', 'trilix', 'zyph']):
        penalty -= 14
    return penalty


def curated_candidate_score(item, form_data):
    name = item.get('name', '') if isinstance(item, dict) else str(item)
    text = ' '.join(str(item.get(key, '')) for key in ['origin', 'style', 'meaning', 'why']).lower() if isinstance(item, dict) else ''
    category = project_type_category(form_data)
    score = sayability_score(name, form_data) + business_style_score(name, form_data) + business_curated_penalty(name, form_data)

    if any(token in text for token in ['generic', 'descriptive only', 'keyword stuffed', 'competitor']):
        score -= 12
    if any(token in text for token in ['suggestive', 'distinctive', 'memorable', 'ownable', 'searchable']):
        score += 6
    if category == 'local_service' and any(token in text for token in ['trust', 'local', 'clear', 'referral']):
        score += 6
    elif category in {'app_product', 'product'} and any(token in text for token in ['distinctive', 'coined', 'short', 'search']):
        score += 6
    elif category == 'nonprofit' and any(token in text for token in ['warm', 'mission', 'community', 'trust']):
        score += 6
    return score


def rank_curated_candidates(names, form_data):
    return sorted(
        names,
        key=lambda item: curated_candidate_score(item, form_data),
        reverse=True,
    )


def summarize_preferences(form_data):
    parts = []
    if form_data.get('pet_type'):
        parts.append(form_data['pet_type'])
    if form_data.get('industry'):
        parts.append(form_data['industry'])
    if form_data.get('business_description'):
        parts.append(form_data['business_description'])
    if form_data.get('target_audience'):
        parts.append(form_data['target_audience'])
    if form_data.get('discovery_style'):
        parts.append(form_data['discovery_style'])
    if form_data.get('style'):
        parts.append(form_data['style'])
    if form_data.get('vibe'):
        parts.append(form_data['vibe'].strip())
    if form_data.get('market_position'):
        parts.append(form_data['market_position'])
    if form_data.get('timeless_vs_distinctive'):
        parts.append(form_data['timeless_vs_distinctive'])
    return " · ".join(parts) if parts else "Open taste"


def pick_phrase(value, mapping, fallback):
    cleaned = (value or '').strip().lower()
    return mapping.get(cleaned, fallback)


def build_editor_note(form_data, used_fallback, round_number):
    dimensions = infer_dimensions(form_data)

    style_phrase = pick_phrase(dimensions['style_vector'], {
        'classic': 'classic, anchored choices',
        'timeless': 'timeless, enduring choices',
        'modern': 'clean, current choices',
        'professional': 'professional, credible choices',
        'friendly': 'friendly, approachable choices',
        'innovative': 'inventive, forward-looking choices',
        'elegant': 'elegant, polished choices',
        'bold': 'bold, confident choices',
        'soft and romantic': 'soft, romantic choices',
        'strong and tailored': 'polished, confident choices',
        'uncommon but usable': 'distinctive choices that still feel easy to live with',
        'balanced': 'balanced choices',
    }, 'balanced choices')

    tone_phrase = pick_phrase(dimensions['tone_vector'], {
        'warm and grounded': 'warm and grounded',
        'soft and gentle': 'soft and gentle',
        'elegant and understated': 'elegant and understated',
        'bright and lively': 'bright and lively',
        'strong and composed': 'strong and composed',
        'romantic and lyrical': 'romantic and lyrical',
        'modern and crisp': 'modern and crisp',
        'distinctive but easy': 'distinctive but easy',
        'playful': 'playful',
        'loyal': 'loyal',
        'elegant': 'elegant',
        'brave': 'brave',
        'curious': 'curious',
        'gentle': 'gentle',
        'mischievous': 'mischievous',
        'regal': 'regal',
        'adventurous': 'adventurous',
        'quirky': 'quirky',
        'sweet': 'sweet',
        'tough': 'tough',
        'open-ended': 'thoughtful and flexible',
        'trustworthy': 'trustworthy',
        'premium': 'premium',
        'technical': 'technical',
        'creative': 'creative',
        'local': 'local',
        'human': 'human',
        'expert': 'expert',
    }, 'thoughtful and flexible')

    market_phrase = pick_phrase(dimensions['market_position'], {
        'fast and dependable': 'for a fast, dependable market position',
        'human and caring': 'for a human, caring market position',
        'polished and premium': 'for a polished, premium market position',
        'local and trusted': 'for a local, trusted market position',
        'bold and modern': 'for a bold, modern market position',
        'operational and no-nonsense': 'for an operational, no-nonsense market position',
        'creative and memorable': 'for a creative, memorable market position',
        'established and professional': 'for an established, professional market position',
        'open-ended': 'without forcing a single market posture',
    }, 'without forcing a single market posture')

    distinctiveness_phrase = pick_phrase(dimensions['distinctiveness_tolerance'], {
        'strongly timeless': 'with a strongly timeless bias',
        'mostly timeless': 'with a clear timeless bias',
        'balanced': 'with a balanced level of distinctiveness',
        'mostly distinctive': 'with a noticeable edge of distinctiveness',
        'strongly distinctive': 'with a bold distinctive edge',
    }, 'with a balanced level of distinctiveness')

    familiarity_phrase = pick_phrase(dimensions['familiarity_preference'], {
        'very familiar and easy': 'while staying very easy to say and live with',
        'recognizable but not overused': 'while staying recognizable without feeling played out',
        'a little less common': 'while leaning a little less common',
        'memorable and rarer': 'while still feeling memorable and rarer',
        'open': 'without boxing you into one familiarity lane',
    }, 'without boxing you into one familiarity lane')

    discovery_phrase = pick_phrase(dimensions['discovery_style'], {
        'classic favorites': 'with a classic-favorites search range',
        'balanced mix': 'with a balanced mix of familiar and fresh ideas',
        'unexpected finds': 'with a more exploratory discovery range',
        'completely original': 'with a highly original discovery range',
        'safe favorites': 'with a safer, broadly agreeable search range',
        'familiar but fresh': 'with familiar-but-fresh discovery range',
        'hidden gems': 'with an underused, hidden-gem bias',
        'bold discoveries': 'with a more adventurous discovery range',
        'surprise me': 'with a wider surprise-me search range',
        'open': 'without forcing one discovery mode',
    }, 'without forcing one discovery mode')

    if round_number == 1:
        opener = 'This first list leans'
    elif round_number == 2:
        opener = 'This refined list leans'
    else:
        opener = 'This final list leans'

    if used_fallback and round_number == 1:
        opener = 'This starter list leans'

    return f"{opener} {style_phrase} with a {tone_phrase} feel, {market_phrase}, {distinctiveness_phrase}, {familiarity_phrase}, {discovery_phrase}."


def build_refine_link(form_data):
    query = urlencode(form_data)
    return f"/?{query}#brief" if query else "/#brief"


def slugify_name(name):
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug or 'name'


def domain_slug(name):
    cleaned = re.sub(r'\band\b', '', (name or '').lower())
    cleaned = re.sub(r'\b(co|company|inc|llc|studio|studios|group)\b', '', cleaned)
    cleaned = re.sub(r'[^a-z0-9]+', '', cleaned)
    return cleaned or 'name'


def domain_status(domain, status='unknown', label=''):
    if not label:
        label = {
            'available': 'Available',
            'taken': 'Taken',
            'premium': 'Premium',
            'not_checked': 'Not verified',
            'unknown': 'Not verified',
        }.get(status, status.replace('_', ' ').title())
    return {
        'domain': domain,
        'status': status,
        'label': label,
        'class': status.replace('_', '-'),
    }


def domain_status_from_godaddy(domain, payload):
    available = payload.get('available') if isinstance(payload, dict) else None
    premium_threshold = int(os.getenv('GODADDY_PREMIUM_PRICE_THRESHOLD', '100000000'))
    price = payload.get('price') if isinstance(payload, dict) else None
    is_premium = bool(payload.get('premium')) if isinstance(payload, dict) else False
    if isinstance(price, int) and price >= premium_threshold:
        is_premium = True

    if available is True:
        if is_premium:
            return domain_status(domain, 'premium', 'Premium')
        return domain_status(domain, 'available', 'Available')
    if available is False:
        return domain_status(domain, 'taken', 'Taken')
    return domain_status(domain)


def load_domain_cache():
    if not DOMAIN_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(DOMAIN_CACHE_PATH.read_text(encoding='utf-8'))
        domains = payload.get('domains', payload) if isinstance(payload, dict) else {}
        return domains if isinstance(domains, dict) else {}
    except Exception:
        app.logger.exception('Failed to load domain cache from %s', DOMAIN_CACHE_PATH)
        return {}


def save_domain_cache(domains):
    try:
        write_json_atomic(DOMAIN_CACHE_PATH, {'domains': domains})
    except Exception:
        app.logger.exception('Failed to save domain cache to %s', DOMAIN_CACHE_PATH)


def cached_domain_status(cache, domain, now):
    cached = cache.get(domain)
    if not isinstance(cached, dict):
        return None
    checked_at = cached.get('checked_at', 0)
    ttl = DOMAIN_UNKNOWN_CACHE_TTL_SECONDS if cached.get('status') in {'unknown', 'not_checked'} else DOMAIN_CACHE_TTL_SECONDS
    if not isinstance(checked_at, (int, float)) or now - checked_at > ttl:
        return None
    return domain_status(domain, cached.get('status', 'unknown'), cached.get('label', ''))


def godaddy_credentials():
    api_key = os.getenv('GODADDY_API_KEY', '').strip()
    api_secret = os.getenv('GODADDY_API_SECRET', '').strip()
    return api_key, api_secret


def godaddy_domain_available(domain):
    api_key, api_secret = godaddy_credentials()
    if not api_key or not api_secret:
        return domain_status(domain, 'not_checked', 'Not checked')

    base_url = os.getenv('GODADDY_API_BASE', 'https://api.godaddy.com').strip().rstrip('/')
    timeout = float(os.getenv('GODADDY_TIMEOUT_SECONDS', '4'))
    url = f"{base_url}/v1/domains/available?domain={quote(domain)}"
    request_headers = {
        'Accept': 'application/json',
        'Authorization': f"sso-key {api_key}:{api_secret}",
    }
    req = Request(url, headers=request_headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
        return domain_status_from_godaddy(domain, payload)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        app.logger.warning('GoDaddy availability check failed for %s: %s', domain, exc)
    except Exception as exc:
        app.logger.exception('Unexpected GoDaddy availability error for %s: %s', domain, exc)
    return domain_status(domain)


def check_domain_availability(domains):
    unique_domains = list(dict.fromkeys(domain for domain in domains if domain))
    if not unique_domains:
        return {}

    api_key, api_secret = godaddy_credentials()
    if not api_key or not api_secret:
        return {domain: domain_status(domain, 'not_checked', 'Not checked') for domain in unique_domains}

    now = time.time()
    cache = load_domain_cache()
    results = {}
    missing_domains = []
    for domain in unique_domains:
        cached = cached_domain_status(cache, domain, now)
        if cached:
            results[domain] = cached
        else:
            missing_domains.append(domain)

    if missing_domains:
        max_workers = min(8, len(missing_domains))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(godaddy_domain_available, domain): domain for domain in missing_domains}
            for future in as_completed(futures):
                domain = futures[future]
                try:
                    status = future.result()
                except Exception as exc:
                    app.logger.exception('Domain availability worker failed for %s: %s', domain, exc)
                    status = domain_status(domain)
                results[domain] = status
                cache[domain] = {
                    'status': status.get('status', 'unknown'),
                    'label': status.get('label', ''),
                    'checked_at': now,
                }
        save_domain_cache(cache)

    return results


def build_domain_info(name):
    base = domain_slug(name)
    ideas = [f"{base}.com", f"get{base}.com", f"{base}.co"]
    if len(base) <= 10:
        ideas.append(f"{base}.io")
    else:
        ideas.append(f"hello{base}.com")
    return {
        'primary': ideas[0],
        'alternatives': ideas[1:],
        'display_domain': ideas[0],
        'display_status': None,
        'note': '',
    }


def choose_display_domain(info, statuses):
    ideas = [info.get('primary'), *(info.get('alternatives') or [])]
    idea_statuses = [
        statuses.get(domain, domain_status(domain))
        for domain in ideas
        if domain
    ]
    if not idea_statuses:
        return info.get('primary'), None

    available = next((status for status in idea_statuses if status.get('status') == 'available'), None)
    if available:
        return available.get('domain'), available

    checked = next(
        (status for status in idea_statuses if status.get('status') not in {'not_checked', 'unknown'}),
        None,
    )
    if checked:
        return checked.get('domain'), checked

    return idea_statuses[0].get('domain'), idea_statuses[0]


def attach_domain_availability(names):
    domains = []
    for item in names:
        info = item.get('domain_info') or {}
        domains.extend([info.get('primary'), *(info.get('alternatives') or [])])

    statuses = check_domain_availability(domains)
    if not statuses:
        return names

    for item in names:
        info = item.get('domain_info')
        if not info:
            continue
        display_domain, display_status = choose_display_domain(info, statuses)
        info['display_domain'] = display_domain
        info['display_status'] = display_status
        info['note'] = ''
    return names


def clean_emotional_opener(value):
    cleaned = re.sub(r'\s+', ' ', (value or '').strip())
    if not cleaned:
        return ''
    cleaned = cleaned.strip(' "\'')
    if not cleaned:
        return ''
    if len(cleaned) > 80:
        cleaned = cleaned[:77].rsplit(' ', 1)[0].rstrip(' ,.:-;') + '...'
    if cleaned[-1] not in '.!?':
        cleaned += '.'
    return cleaned


def infer_curated_emotional_opener(item, form_data):
    text = ' '.join(
        str(value or '').lower()
        for value in [
            item.get('style'),
            item.get('why'),
            form_data.get('style'),
            form_data.get('vibe'),
            form_data.get('discovery_style'),
            form_data.get('notes'),
        ]
    )
    if any(token in text for token in ['nature', 'botanical', 'sea', 'coastal', 'forest', 'woodland']):
        return 'Grounded natural warmth.'
    if any(token in text for token in ['classic', 'timeless', 'vintage']):
        return 'Quietly timeless.'
    if any(token in text for token in ['elegant', 'refined', 'polished']):
        return 'Elegant without trying.'
    if any(token in text for token in ['strong', 'masculine', 'bold']):
        return 'Soft strength.'
    if any(token in text for token in ['international', 'bilingual', 'cross-cultural', 'global']):
        return 'Easy across worlds.'
    if any(token in text for token in ['distinctive', 'uncommon', 'hidden', 'rare']):
        return 'Distinctive, but wearable.'
    if any(token in text for token in ['gentle', 'soft', 'warm']):
        return 'Warm and easy to picture.'
    return 'Quiet confidence.'


def infer_original_emotional_opener(item, form_data):
    text = ' '.join(
        str(value or '').lower()
        for value in [
            item.get('style'),
            item.get('why'),
            item.get('fit_note'),
            form_data.get('style'),
            form_data.get('vibe'),
            form_data.get('discovery_style'),
            form_data.get('notes'),
        ]
    )
    if any(token in text for token in ['coastal', 'sea', 'ocean', 'nature']):
        return 'New, calm, and wearable.'
    if any(token in text for token in ['romantic', 'elegant', 'french', 'italian']):
        return 'Invented, but polished.'
    if any(token in text for token in ['soft', 'gentle']):
        return 'Softly original.'
    if any(token in text for token in ['bold', 'distinctive', 'rare']):
        return 'Rare by design.'
    if any(token in text for token in ['modern', 'clean']):
        return 'Fresh, but name-like.'
    return 'Invented, but believable.'


def enrich_name(item, form_data, index, total):
    enriched = dict(item)
    enriched['slug'] = slugify_name(item['name'])
    enriched['rank_label'] = f"{index} / {total}"
    enriched['standout'] = index <= 2
    enriched['emotional_opener'] = clean_emotional_opener(
        enriched.get('emotional_opener') or infer_curated_emotional_opener(enriched, form_data)
    )
    tone = (form_data.get('vibe') or 'thoughtful').lower()
    enriched['fit_note'] = (
        f"{item['name']} suits a {((form_data.get('style') or 'balanced').lower())} direction"
        f" with a {tone} feel."
    )
    enriched['pairing_note'] = (
        "It carries enough personality to stand on its own, while still feeling easy to say every day."
    )
    enriched['why_detail'] = (
        f"{item['why']} It has the kind of shape and tone that tends to keep sounding good after the novelty wears off."
    )
    enriched['domain_info'] = build_domain_info(item['name'])
    return enriched


def enrich_names(names, form_data):
    enriched = [enrich_name(item, form_data, index + 1, len(names)) for index, item in enumerate(names)]
    return attach_domain_availability(enriched)


def parse_reactions(source):
    reactions = {}
    if not source:
        return reactions
    for key, value in source.items():
        if not key.startswith('reaction__'):
            continue
        clean_value = (value or '').strip()
        if clean_value in REACTION_LABELS:
            reactions[key.split('reaction__', 1)[1]] = clean_value
    return reactions


def build_reaction_summary(names, reactions):
    buckets = {key: [] for key in REACTION_LABELS}
    for item in names:
        reaction = reactions.get(item['slug'])
        if reaction in buckets:
            buckets[reaction].append(item['name'])

    summary_lines = []
    if buckets['love']:
        summary_lines.append(f"Strong yeses: {', '.join(buckets['love'])}.")
    if buckets['maybe']:
        summary_lines.append(f"Maybes worth refining around: {', '.join(buckets['maybe'])}.")

    friction_phrases = []
    for key in ['no', 'too_trendy', 'too_soft', 'too_common', 'hard_to_pronounce']:
        if buckets[key]:
            friction_phrases.append(f"{REACTION_LABELS[key]}: {', '.join(buckets[key])}")
    if friction_phrases:
        summary_lines.append("Move away from signals — " + "; ".join(friction_phrases) + ".")

    return " ".join(summary_lines) or "No reactions supplied yet."


def build_reaction_effect_note(names, reactions):
    buckets = {key: [] for key in REACTION_LABELS}
    for item in names:
        reaction = reactions.get(item['slug'])
        if reaction in buckets:
            buckets[reaction].append(item['name'])

    if not any(buckets.values()):
        return ''

    friction_count = sum(len(buckets[key]) for key in ['no', 'too_trendy', 'too_soft', 'too_common', 'hard_to_pronounce'])
    loved_text = ", ".join(buckets['love'][:3])
    maybe_text = ", ".join(buckets['maybe'][:2])

    if buckets['love'] and buckets['maybe'] and friction_count:
        return f"We leaned toward {loved_text}, kept {maybe_text} nearby, and moved away from the names you ruled out."
    if buckets['love'] and friction_count:
        return f"We leaned toward {loved_text} and moved away from the names you ruled out."
    if buckets['love']:
        return f"We leaned further into the feeling of {loved_text}."
    if buckets['maybe'] and friction_count:
        return f"We refined around {maybe_text} and moved away from the names you ruled out."
    if buckets['maybe']:
        return "We used those maybes as the next direction."
    return "We moved away from the names you ruled out."


def build_taste_summary_note(form_data, reactions, names):
    buckets = {key: [] for key in REACTION_LABELS}
    by_name = {item['name']: item for item in names}
    for item in names:
        reaction = reactions.get(item['slug'])
        if reaction in buckets:
            buckets[reaction].append(item['name'])

    loved = buckets['love']
    maybes = buckets['maybe']
    if not loved and not maybes:
        return ''

    loved_styles = []
    for name in loved:
        style = (by_name.get(name, {}).get('style') or '').strip().lower()
        if style and style not in loved_styles:
            loved_styles.append(style)

    style_phrase = loved_styles[0] if loved_styles else (form_data.get('style') or 'balanced').strip().lower()
    vibe_phrase = (form_data.get('vibe') or '').strip().lower()
    loved_text = human_join(loved[:3])
    maybe_text = human_join(maybes[:2])

    if loved and maybe_text:
        return f"{style_phrase.capitalize()} names like {loved_text}, with {maybe_text} still nearby."
    if loved:
        return f"{style_phrase.capitalize()} names like {loved_text}."
    if maybe_text and vibe_phrase:
        return f"{vibe_phrase.capitalize()} names near {maybe_text}."
    return f"Names near {maybe_text}."


def infer_taste_profile(form_data, reactions, names):
    loved = []
    maybes = []
    disliked = []

    for item in names:
        reaction = reactions.get(item['slug'])
        if reaction == 'love':
            loved.append(item['name'])
        elif reaction == 'maybe':
            maybes.append(item['name'])
        elif reaction:
            disliked.append(item['name'])

    sentences = []
    if loved:
        sentences.append(f"You seem drawn to names like {', '.join(loved[:3])} that feel {', '.join(sorted({item['style'] for item in names if item['name'] in loved})[:2])}.")
    if maybes:
        sentences.append(f"There is also interest in {', '.join(maybes[:3])}, so a nearby-but-sharper lane makes sense.")
    if disliked:
        sentences.append(f"You are clearly moving away from {', '.join(disliked[:3])} style territory.")

    style = (form_data.get('style') or 'balanced').lower()
    vibe = (form_data.get('vibe') or 'thoughtful').lower()
    if not sentences:
        sentences.append(f"Your taste reads as {style}, {vibe}, and open to refinement.")

    return " ".join(sentences)


def describe_name_sound(name):
    pronunciation = (name.get('pronunciation') or name.get('name') or '').strip()
    clean = re.sub(r'[^A-Za-z]', '', pronunciation)
    if not clean:
        return 'Clear sound. Easy to hold onto.'
    first = clean[0].upper()
    last = clean[-1].lower()
    opening = 'Strong opening' if first in 'BCDGJKPTVZ' else 'Soft opening'
    finish = 'soft finish' if last in 'aeilnrs' else 'crisp finish'
    return f"{opening}. {finish.capitalize()}."


def build_personality_words(name, form_data):
    text = ' '.join([
        str(name.get('style') or ''),
        str(name.get('why') or ''),
        str(name.get('fit_note') or ''),
        str(form_data.get('style') or ''),
        str(form_data.get('vibe') or ''),
    ]).lower()
    options = [
        ('warm', 'Warm'),
        ('gentle', 'Gentle'),
        ('soft', 'Gentle'),
        ('classic', 'Timeless'),
        ('timeless', 'Timeless'),
        ('elegant', 'Elegant'),
        ('refined', 'Elegant'),
        ('strong', 'Steady'),
        ('grounded', 'Grounded'),
        ('bright', 'Bright'),
        ('lively', 'Bright'),
        ('romantic', 'Romantic'),
        ('distinctive', 'Distinctive'),
        ('uncommon', 'Distinctive'),
        ('modern', 'Modern'),
    ]
    words = []
    for token, label in options:
        if token in text and label not in words:
            words.append(label)
        if len(words) == 3:
            break
    return words or ['Thoughtful', 'Wearable', 'Steady']


def build_detail_profile(selected, names, form_data):
    related = [item for item in names if item['slug'] != selected['slug']]
    return {
        'first_impression': selected.get('emotional_opener') or infer_curated_emotional_opener(selected, form_data),
        'personality': build_personality_words(selected, form_data),
        'sound': describe_name_sound(selected),
        'fits_parents_who_like': [item['name'] for item in related[:4]],
        'similar_feeling': [item['name'] for item in related[4:8] or related[:4]],
        'why_taste': selected.get('why_detail') or selected.get('fit_note') or selected.get('why'),
    }


def build_refinement_note(form_data, reactions, names, next_round_number):
    summary = build_reaction_summary(names, reactions)
    return (
        f"Use the user's prior-round reactions as high-signal feedback for a sharper {round_word(next_round_number)}-round list. "
        "Keep the emotional lane they liked, strengthen what got 'love' and 'maybe', and deliberately move away from friction tags. "
        f"Reaction summary: {summary}"
    )


def reaction_progress(names, reactions):
    completed = sum(1 for item in names if reactions.get(item['slug']))
    total = len(names)
    return completed, total


def load_share_store():
    if not SHARE_STORE_PATH.exists():
        return {}
    try:
        return json.loads(SHARE_STORE_PATH.read_text(encoding='utf-8'))
    except Exception:
        app.logger.exception('Failed to load share store from %s', SHARE_STORE_PATH)
        return {}


def save_share_store(payload):
    write_json_atomic(SHARE_STORE_PATH, payload)


def load_feedback_store():
    if not FEEDBACK_STORE_PATH.exists():
        return []
    try:
        payload = json.loads(FEEDBACK_STORE_PATH.read_text(encoding='utf-8'))
        return payload if isinstance(payload, list) else []
    except Exception:
        app.logger.exception('Failed to load feedback store from %s', FEEDBACK_STORE_PATH)
        return []


def save_feedback_store(payload):
    write_json_atomic(FEEDBACK_STORE_PATH, payload)


def clean_feedback_value(value, max_length=1200):
    return (value or '').strip()[:max_length]


def feedback_admin_allowed():
    token = os.getenv('FEEDBACK_ADMIN_TOKEN', '').strip()
    if not token:
        return False
    return request.args.get('token', '') == token


def build_feedback_admin_link():
    token = os.getenv('FEEDBACK_ADMIN_TOKEN', '').strip()
    return f"{url_for('feedback_responses')}?token={token}" if token else ''


def feedback_enabled():
    return os.getenv('FEEDBACK_ENABLED', 'true').strip().lower() not in {'0', 'false', 'no', 'off'}


def live_brief_enabled():
    return os.getenv('LIVE_BRIEF_ENABLED', 'true').strip().lower() not in {'0', 'false', 'no', 'off'}


def feedback_client_key():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',', 1)[0].strip()
    return request.remote_addr or 'unknown'


def feedback_is_rate_limited(window_seconds=180):
    now = datetime.now(timezone.utc).timestamp()
    key = feedback_client_key()
    last_seen = FEEDBACK_RATE_LIMIT.get(key, 0)
    FEEDBACK_RATE_LIMIT[key] = now
    return now - last_seen < window_seconds


def feedback_looks_spammy(source):
    if clean_feedback_value(source.get('company_website'), 200):
        return True
    fields = [
        source.get('liked_most', ''),
        source.get('confusing', ''),
        source.get('missing', ''),
        source.get('bug', ''),
        source.get('other_notes', ''),
    ]
    combined = ' '.join(fields).lower()
    if len(re.findall(r'https?://|www\\.', combined)) > 1:
        return True
    spam_terms = [
        'crypto', 'casino', 'viagra', 'loan', 'forex', 'backlink',
        'telegram @', 'whatsapp', 'seo services', 'adult content',
    ]
    return any(term in combined for term in spam_terms)


def feedback_sheet_headers():
    return [
        'Created At', 'Name', 'Email', 'Tester Type', 'Overall Rating',
        'Used Original', 'Would Share', 'Liked Most', 'Confusing',
        'Missing', 'Bug', 'Other Notes', 'Page URL', 'User Agent', 'Status',
    ]


def feedback_sheet_row(entry):
    return [
        entry.get('created_at', ''),
        entry.get('name', ''),
        entry.get('email', ''),
        entry.get('tester_type', ''),
        entry.get('overall_rating', ''),
        entry.get('used_original', ''),
        entry.get('would_share', ''),
        entry.get('liked_most', ''),
        entry.get('confusing', ''),
        entry.get('missing', ''),
        entry.get('bug', ''),
        entry.get('other_notes', ''),
        entry.get('page_url', ''),
        entry.get('user_agent', ''),
        entry.get('status', 'new'),
    ]


def append_feedback_to_google_sheet(entry):
    sheet_id = os.getenv('GOOGLE_FEEDBACK_SHEET_ID', '').strip()
    credentials_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
    if not sheet_id or not credentials_json or gspread is None:
        return False
    credentials = json.loads(credentials_json)
    client = gspread.service_account_from_dict(credentials)
    worksheet_name = os.getenv('GOOGLE_FEEDBACK_WORKSHEET', 'Feedback').strip() or 'Feedback'
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=20)
        worksheet.append_row(feedback_sheet_headers())
    if not worksheet.row_values(1):
        worksheet.append_row(feedback_sheet_headers())
    worksheet.append_row(feedback_sheet_row(entry), value_input_option='USER_ENTERED')
    return True


def store_feedback(source):
    if feedback_looks_spammy(source) or feedback_is_rate_limited():
        return None

    feedback_store = load_feedback_store()
    entry = {
        'id': secrets.token_urlsafe(8),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'new',
        'name': clean_feedback_value(source.get('name'), 120),
        'email': clean_feedback_value(source.get('email'), 180),
        'tester_type': clean_feedback_value(source.get('tester_type'), 80),
        'overall_rating': clean_feedback_value(source.get('overall_rating'), 20),
        'used_original': clean_feedback_value(source.get('used_original'), 20),
        'would_share': clean_feedback_value(source.get('would_share'), 20),
        'liked_most': clean_feedback_value(source.get('liked_most')),
        'confusing': clean_feedback_value(source.get('confusing')),
        'missing': clean_feedback_value(source.get('missing')),
        'bug': clean_feedback_value(source.get('bug')),
        'other_notes': clean_feedback_value(source.get('other_notes')),
        'page_url': clean_feedback_value(source.get('page_url'), 500),
        'user_agent': clean_feedback_value(request.headers.get('User-Agent'), 300),
    }
    try:
        if append_feedback_to_google_sheet(entry):
            return entry
    except Exception:
        app.logger.exception('Failed to append feedback to Google Sheet')

    feedback_store.append(entry)
    save_feedback_store(feedback_store[-500:])
    return entry


def generate_fallback_results(exclude_names=None, form_data=None):
    exclude = {name.lower() for name in (exclude_names or [])}
    candidates = [item for item in FALLBACK_NAMES if item['name'].lower() not in exclude]
    if len(candidates) < 8:
        candidates = FALLBACK_NAMES[:]
    form_data = form_data or {}
    candidates = sorted(
        candidates,
        key=lambda item: (
            curated_candidate_score(item, form_data),
            sayability_score(item.get('name'), form_data),
            business_style_score(item.get('name'), form_data),
            random.random(),
        ),
        reverse=True,
    )
    return candidates[:min(8, len(candidates))]


def generate_names(form_data, refinement_note='', exclude_names=None):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key or OpenAI is None:
        return generate_fallback_results(exclude_names=exclude_names, form_data=form_data), True

    try:
        client = OpenAI(api_key=api_key)
        details = build_details(form_data, refinement_note=refinement_note)
        if exclude_names:
            details += "\n\nDO NOT REPEAT THESE ALREADY-SHOWN NAMES:\n" + "\n".join(f"- {name}" for name in exclude_names)
        response = client.responses.create(
            model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
            input=PROMPT_TEMPLATE.format(details=details),
            text={"format": {"type": "json_schema", "name": "business_names", "schema": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "pronunciation": {"type": "string"},
                                "origin": {"type": "string"},
                                "style": {"type": "string"},
                                "meaning": {"type": "string"},
                                "emotional_opener": {"type": "string"},
                                "why": {"type": "string"}
                            },
                            "required": ["name", "pronunciation", "origin", "style", "meaning", "emotional_opener", "why"],
                            "additionalProperties": False
                        },
                        "minItems": 8,
                        "maxItems": 8
                    }
                },
                "required": ["names"],
                "additionalProperties": False
            }}}
        )
        raw_text = getattr(response, 'output_text', '') or ''
        payload = json.loads(raw_text) if raw_text else {}
        names = payload.get('names', []) if isinstance(payload, dict) else []
        if names:
            return rank_curated_candidates(names, form_data), False
        app.logger.warning('OpenAI response parsed but returned no names payload. Raw text: %s', raw_text)
    except Exception as exc:
        app.logger.exception('OpenAI generation failed: %s', exc)

    return generate_fallback_results(exclude_names=exclude_names, form_data=form_data), True


def store_shortlist(shortlist):
    shortlist_id = secrets.token_urlsafe(8)
    SHORTLIST_STORE[shortlist_id] = shortlist
    if len(SHORTLIST_STORE) > MAX_SHORTLISTS:
        oldest = next(iter(SHORTLIST_STORE))
        SHORTLIST_STORE.pop(oldest, None)
    return shortlist_id


def ancestry_shortlist_ids(shortlist):
    seen = []
    current = shortlist
    while current:
        current_id = current.get('shortlist_id')
        if current_id:
            seen.append(current_id)
        parent_id = current.get('parent_shortlist_id')
        if not parent_id:
            break
        current = SHORTLIST_STORE.get(parent_id)
    return seen


def collect_seen_names(shortlist):
    seen_names = []
    current = shortlist
    while current:
        seen_names.extend(item['name'] for item in current.get('names', []))
        parent_id = current.get('parent_shortlist_id')
        if not parent_id:
            break
        current = SHORTLIST_STORE.get(parent_id)
    return list(dict.fromkeys(seen_names))


def build_next_actions(round_number):
    refinement_count = max(0, round_number - 1)
    has_more_refinement = refinement_count < MAX_REFINEMENT_ROUNDS
    next_round_number = round_number + 1
    return {
        'can_refine': has_more_refinement,
        'next_round_number': next_round_number,
        'next_round_label': make_round_label(next_round_number),
        'next_refinement_label': make_refinement_label(next_round_number),
        'next_pass_phrase': f"sharper {round_word(next_round_number)} pass",
        'final_round_reached': not has_more_refinement,
    }


def serialize_form_data(form_data):
    return {key: form_data.get(key, '') for key in DEFAULT_FORM_DATA}


def serialize_names(names):
    keys = ['name', 'pronunciation', 'origin', 'style', 'meaning', 'emotional_opener', 'why', 'slug', 'rank_label', 'standout', 'highlight', 'fit_note', 'pairing_note', 'why_detail', 'structure', 'originality_note', 'domain_info']
    return [{key: item.get(key) for key in keys} for item in names]


def base_url():
    configured = os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/')
    if configured:
        return configured
    return request.url_root.rstrip('/')


def absolute_url(path):
    if not path:
        return base_url()
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return f"{base_url()}{path if path.startswith('/') else '/' + path}"


def build_share_meta(payload, mode='shortlist'):
    image_url = absolute_url(url_for('static', filename='images/namengine-business-card-share-v2.jpg'))
    if mode == 'original':
        names = ', '.join(item['name'] for item in payload.get('names', [])[:3])
        title = 'Original business names by NamEngine Business'
        description = f"A custom business-name set from NamEngine Business — {names}." if names else 'Original business names created by NamEngine Business.'
    else:
        names = ', '.join(item['name'] for item in payload.get('names', [])[:3])
        title = 'Your NamEngine Business list'
        description = f"A thoughtful business-name list from NamEngine Business — {names}." if names else 'A thoughtful business-name list from NamEngine Business.'
    return {
        'meta_title': title,
        'meta_description': description,
        'meta_image': image_url,
        'meta_image_width': 1200,
        'meta_image_height': 630,
        'meta_image_type': 'image/jpeg',
    }


def build_share_message(shortlist):
    top_names = ', '.join(item['name'] for item in shortlist['names'][:3])
    return f"Here’s my NamEngine Business list — {top_names}. Curious what you think. Powered by NamEngine Business."


def build_original_share_message(payload):
    top_names = ', '.join(item['name'] for item in payload['names'][:3])
    return f"Here are the original business names NamEngine Business created for me — {top_names}. Curious what you think."


def build_chosen_share_message(payload):
    name = payload.get('name', {}).get('name', 'this name')
    return f"I chose {name} with NamEngine Business. Curious what you think."


def build_chosen_share_meta(payload):
    name = payload.get('name', {}).get('name', 'A chosen business name')
    image_url = absolute_url(url_for('static', filename='images/namengine-business-card-share-v2.jpg'))
    return {
        'meta_title': f"I chose {name} | NamEngine Business",
        'meta_description': f"A chosen business name from NamEngine Business: {name}.",
        'meta_image': image_url,
        'meta_image_width': 1200,
        'meta_image_height': 630,
        'meta_image_type': 'image/jpeg',
    }


def create_share_snapshot(shortlist):
    share_store = load_share_store()
    share_id = secrets.token_urlsafe(8)
    share_store[share_id] = {
        'mode': 'shortlist',
        'round_number': shortlist['round_number'],
        'round_label': shortlist['round_label'],
        'preference_summary': shortlist['preference_summary'],
        'editor_note': shortlist['editor_note'],
        'form_data': serialize_form_data(shortlist['form_data']),
        'names': serialize_names(shortlist['names']),
        'reactions': dict(shortlist.get('reactions', {})),
        'reaction_summary': shortlist.get('reaction_summary', ''),
        'taste_profile': shortlist.get('taste_profile', ''),
        'taste_summary_note': shortlist.get('taste_summary_note', ''),
        'shared_message': build_share_message(shortlist),
        'powered_by': 'Powered by NamEngine Business',
        'created_from_shortlist': shortlist['shortlist_id'],
    }
    save_share_store(share_store)
    return share_id


def create_original_share_snapshot(payload):
    share_store = load_share_store()
    share_id = secrets.token_urlsafe(8)
    share_store[share_id] = {
        'mode': 'original',
        'original_summary': payload['original_summary'],
        'editorial_note': payload['editorial_note'],
        'form_data': dict(payload['form_data']),
        'names': payload['names'],
        'tune_history': list(payload.get('tune_history', [])),
        'shared_message': build_original_share_message(payload),
        'powered_by': 'Powered by NamEngine Business',
    }
    save_share_store(share_store)
    return share_id


def create_chosen_name_snapshot(source_share_id, slug):
    share_store = load_share_store()
    source_payload = share_store.get(source_share_id)
    if not source_payload:
        abort(404)

    selected = next((item for item in source_payload.get('names', []) if item.get('slug') == slug), None)
    if not selected:
        abort(404)

    source_mode = source_payload.get('mode', 'shortlist')
    source_label = 'Original Business Name Studio' if source_mode == 'original' else source_payload.get('round_label', 'Business name list')
    chosen_id = secrets.token_urlsafe(8)
    payload = {
        'mode': 'chosen',
        'source_mode': source_mode,
        'source_label': source_label,
        'source_share_id': source_share_id,
        'name': selected,
        'form_data': dict(source_payload.get('form_data', {})),
        'preference_summary': source_payload.get('preference_summary') or source_payload.get('original_summary') or 'Chosen business name',
        'editor_note': source_payload.get('editor_note') or source_payload.get('editorial_note') or '',
        'powered_by': 'Powered by NamEngine Business',
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    payload['shared_message'] = build_chosen_share_message(payload)
    share_store[chosen_id] = payload
    save_share_store(share_store)
    return chosen_id


def get_share_payload_or_404(share_id):
    share_store = load_share_store()
    payload = share_store.get(share_id)
    if not payload:
        abort(404)
    return payload


def summarize_original_preferences(form_data, tune_direction=''):
    parts = []
    for key in ['pet_type', 'industry', 'business_description', 'target_audience', 'discovery_style', 'style', 'vibe', 'market_position', 'cultural_context', 'starting_letter', 'length_preference']:
        value = form_data.get(key)
        if value:
            parts.append(value)
    if tune_direction:
        parts.append(f'Tuned {ORIGINAL_TUNE_LABELS.get(tune_direction, tune_direction.replace("_", " "))}')
    return ' · '.join(parts) if parts else 'Original name direction'


def build_original_editor_note(form_data, tune_direction=''):
    style = (form_data.get('style') or 'balanced').lower()
    vibe = (form_data.get('vibe') or 'open-ended').lower()
    industry = (form_data.get('industry') or 'open industry').lower()
    market_position = (form_data.get('market_position') or 'open market feel').lower()
    discovery_style = (form_data.get('discovery_style') or 'balanced discovery').lower()
    cultural_feel = (form_data.get('cultural_context') or '').lower()
    starting_letter = (form_data.get('starting_letter') or 'an open starting letter').strip()
    length = (form_data.get('length_preference') or 'balanced length').lower()
    tune_label = ORIGINAL_TUNE_LABELS.get(tune_direction, tune_direction.replace('_', ' '))
    tune_phrase = f" This pass leans {tune_label.lower()}." if tune_direction else ''
    cultural_phrase = f", while carrying {format_cultural_feel_phrase(cultural_feel)}" if cultural_feel else ''
    return (
        f"These names are for {industry}, lean {style}, {vibe}, {market_position}, and {discovery_style}{cultural_phrase}, with {starting_letter.lower()} as the starting cue and a {length} shape.{tune_phrase}"
    )


def format_original_discovery_style(discovery_style):
    style = (discovery_style or '').strip()
    descriptions = {
        'Classic favorites': 'Classic favorites: conservative, broadly wearable coined names; avoid established real names.',
        'Balanced mix': 'Balanced mix: approachable coined names with some freshness and some familiarity.',
        'Unexpected finds': 'Unexpected finds: more exploratory coined names that still feel callable.',
        'Completely original': 'Completely original: the boldest coined-name lane, while staying usable for a real business.',
        'Safe favorites': 'Safe favorites: conservative, broadly wearable coined names; avoid established real names.',
        'Familiar but fresh': 'Familiar but fresh: approachable coined names with a recognizable rhythm and a fresh shape.',
        'Hidden gems': 'Hidden gems: underused-feeling coined names that still sound livable.',
        'Bold discoveries': 'Bold discoveries: more adventurous coined names, while staying pronounceable and human.',
        'Surprise me': 'Surprise me: a wider range of coined names, from grounded to more unexpected.',
    }
    return descriptions.get(style, style or 'Open')


def build_original_details(form_data, tune_direction='', previous_names=None, reaction_note=''):
    previous_names = previous_names or []
    tune_label = ORIGINAL_TUNE_LABELS.get(tune_direction, tune_direction.replace('_', ' ')) if tune_direction else ''
    sections = [
        ('CORE DIRECTION', [
            f"Project type: {form_data.get('pet_type') or 'Open'}",
            f"Industry/category: {form_data.get('industry') or 'Open'}",
            f"Discovery style: {format_original_discovery_style(form_data.get('discovery_style'))}",
            f"Current tuning request: {tune_label or 'First pass'}",
        ]),
        ('BUSINESS CONTEXT / POSITIONING', [
            f"What the business does: {form_data.get('business_description') or 'Not specified'}",
            f"Who it serves: {form_data.get('target_audience') or 'Not specified'}",
            f"Additional business context: {form_data.get('notes') or 'No extra notes supplied.'}",
        ]),
        ('TASTE SIGNALS', [
            f"Core style: {form_data.get('style') or 'Balanced'}",
            f"Immediate signal: {form_data.get('vibe') or 'Open-ended'}",
            f"Market feel: {form_data.get('market_position') or 'Open-ended'}",
            f"Naming direction: {form_data.get('cultural_context') or 'No preference'}",
            f"Familiarity preference: {form_data.get('familiarity_preference') or 'Open'}",
        ]),
        ('USABILITY SIGNALS', [
            f"Say / remember: {form_data.get('pronunciation_importance') or 'Moderate'}",
            f"Starting letter: {form_data.get('starting_letter') or 'Open'}",
            f"Length preference: {form_data.get('length_preference') or 'Balanced'}",
            f"Avoid feeling like: {form_data.get('avoid_feel') or 'No explicit avoidances'}",
        ]),
        ('BRAND-NAMING SIGNALS', [
            business_research_guidance(form_data),
            'Use brand-naming research quietly as ranking guidance, not as user-facing explanation or legal advice.',
        ]),
        ('PREVIOUS NAMES TO AVOID', [
            *(previous_names or ['No previous names supplied.']),
        ]),
    ]
    if reaction_note:
        sections.append(('REACTION SIGNALS FROM THE LAST SET', [reaction_note]))
    lines = []
    for heading, items in sections:
        lines.append(f"{heading}:")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).strip()


def parse_history_field(raw_value):
    if not raw_value:
        return []
    return [item for item in raw_value.split('||') if item]


def slug_similarity(a, b):
    a = slugify_name(a)
    b = slugify_name(b)
    if not a or not b:
        return 0.0
    overlap = len(set(a) & set(b))
    return overlap / max(len(set(a) | set(b)), 1)


def build_original_name_parts(profile):
    style = (profile.get('style') or '').lower()
    vibe = (profile.get('vibe') or '').lower()
    market_position = (profile.get('market_position') or '').lower()
    pet_type = (profile.get('pet_type') or '').lower()
    industry = (profile.get('industry') or '').lower()
    business_description = (profile.get('business_description') or '').lower()
    requested_start = re.sub(r'[^a-z]', '', (profile.get('starting_letter') or '').lower())[:2]

    starts = ['Al', 'El', 'Ma', 'Va', 'Ro', 'Sa', 'Li', 'No', 'Ca', 'Ev', 'Ser', 'La', 'Mar', 'Ori', 'Ari']
    middles = ['ve', 'ria', 'len', 'ora', 'eli', 'ara', 'ine', 'io', 'una', 'eva', 'ari', 'oma', 'era', 'ilo']
    ends = ['a', 'ia', 'en', 'el', 'in', 'ine', 'or', 'is', 'on', 'elle', 'ara', 'o']

    if 'staffing' in industry or 'recruit' in industry or 'staffing' in business_description:
        starts = unique_ordered(['Ready', 'Relay', 'Shift', 'Crew', 'Bridge', 'Field', *starts])
        middles = unique_ordered(['well', 'line', 'path', 'mark', 'on', *middles])
        ends = unique_ordered(['well', 'line', 'works', 'path', 'on', *ends])

    if 'strong' in style or 'strong' in vibe or 'dependable' in market_position or 'no-nonsense' in market_position:
        starts = unique_ordered(['Ca', 'Da', 'Ro', 'Ta', 'Ke', 'Ma', 'Va', 'Re', 'Tor', 'Cal', 'Nor', *starts])
        middles = unique_ordered(['el', 'ar', 'en', 'or', 'ai', 'ev', 'ra', 'io', 'an', *middles])
        ends = unique_ordered(['en', 'or', 'an', 'el', 'is', 'on', 'ar', *ends])
    elif 'soft' in style or 'romantic' in vibe:
        starts = ['A', 'Eli', 'Lu', 'No', 'Sere', 'Mira', 'Ava', 'Elo', 'Vi', 'Lia', 'Ori']
        middles = ['vel', 'ria', 'lia', 'ena', 'ora', 'avi', 'esi', 'una', 'elle', 'ira']
        ends = ['a', 'ia', 'elle', 'ine', 'ara', 'ina', 'ea']
    elif 'modern' in style or 'crisp' in vibe or 'bright' in vibe or 'modern' in market_position:
        starts = unique_ordered(['Ze', 'Ka', 'Lo', 'Ari', 'Novi', 'Tali', 'Vero', 'Cai', 'Rumi', *starts])
        middles = unique_ordered(['ra', 'vi', 'lo', 'en', 'ari', 'esa', 'ori', *middles])
        ends = unique_ordered(['a', 'o', 'en', 'is', 'el', 'in', *ends])

    tune_direction = (profile.get('tune_direction') or '').lower()
    if tune_direction == 'softer':
        starts = ['A', 'Eli', 'Ila', 'Lia', 'Lumi', 'Mira', 'Noa', 'Ora', 'Sera', 'Vela']
        middles = ['lia', 'ora', 'elle', 'ina', 'ara', 'emi', 'una', 'avi']
        ends = ['a', 'ia', 'elle', 'ina', 'ara', 'ea']
    elif tune_direction == 'more_classic':
        starts = ['Ad', 'An', 'Be', 'Cl', 'El', 'Jul', 'Lu', 'Ma', 'Ro', 'Theo']
        middles = ['ar', 'el', 'en', 'ia', 'len', 'ora', 'ine', 'ton']
        ends = ['a', 'ia', 'ine', 'en', 'el', 'or', 'on']
    elif tune_direction == 'more_modern':
        starts = ['Ari', 'Cai', 'Evo', 'Kai', 'Lio', 'Novi', 'Rumi', 'Tavi', 'Vero', 'Zai']
        middles = ['vi', 'ra', 'lo', 'en', 'ari', 'on', 'esa', 'io']
        ends = ['a', 'o', 'en', 'is', 'el', 'in']
    elif tune_direction == 'more_distinctive':
        starts = ['Auri', 'Cal', 'Evo', 'Ivo', 'Lior', 'Mavi', 'Nira', 'Sola', 'Vey', 'Zora']
        middles = ['en', 'ari', 'ova', 'iel', 'ira', 'oza', 'une', 'ev']
        ends = ['a', 'ia', 'en', 'el', 'is', 'or', 'on']

    cultural_feel = (profile.get('cultural_context') or '').lower()
    cultural_parts = CULTURAL_SOUND_PARTS.get(cultural_feel)
    if cultural_parts:
        cultural_starts, cultural_middles, cultural_ends = cultural_parts
        starts = unique_ordered([*cultural_starts, *starts[:6]])
        middles = unique_ordered([*cultural_middles, *middles[:6]])
        ends = unique_ordered([*cultural_ends, *ends[:6]])

    combined_project = f"{pet_type} {industry} {business_description}"
    if any(token in combined_project for token in ['app', 'software', 'platform', 'tool', 'saas']):
        starts = unique_ordered(['Nova', 'Vero', 'Kite', 'Luma', 'Signal', 'Orbit', *starts])
        ends = unique_ordered(['o', 'a', 'io', 'ly', 'on', *ends])
    elif any(token in combined_project for token in ['product', 'goods']):
        starts = unique_ordered(['Modo', 'Cove', 'Keen', 'Vera', 'Sola', 'Trove', *starts])
        ends = unique_ordered(['a', 'o', 'er', 'on', 'ly', *ends])
    elif any(token in combined_project for token in ['studio', 'agency', 'creative', 'consult']):
        starts = unique_ordered(['Aster', 'Cedar', 'North', 'Vale', 'Morrow', 'Blue', *starts])
        middles = unique_ordered(['ly', 'en', 'ra', 'well', 'field', 'line', *middles])
        ends = unique_ordered(['a', 'on', 'er', 'ly', 'well', 'field', *ends])
    elif any(token in combined_project for token in ['nonprofit', 'foundation', 'community']):
        starts = unique_ordered(['Open', 'Common', 'Root', 'Rise', 'Bridge', 'Kind', *starts])
        ends = unique_ordered(['a', 'on', 'well', 'rise', 'root', *ends])
    elif any(token in combined_project for token in ['newsletter', 'media', 'content', 'publication']):
        starts = unique_ordered(['Signal', 'Brief', 'Field', 'Margin', 'North', 'Daily', *starts])
        ends = unique_ordered(['note', 'brief', 'letter', 'daily', 'line', *ends])

    if requested_start:
        starts = [requested_start.capitalize(), requested_start[:1].upper() + 'a', requested_start[:1].upper() + 'e'] + starts

    return starts, middles, ends


def unique_ordered(items):
    seen = set()
    result = []
    for item in items:
        cleaned = str(item)
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def syllable_count(name):
    groups = re.findall(r'[aeiouy]+', re.sub(r'[^a-z]', '', name.lower()))
    return max(1, len(groups))


def fits_length_preference(name, preference):
    cleaned = re.sub(r'[^a-z]', '', name.lower())
    syllables = syllable_count(cleaned)
    preference = (preference or '').lower()
    if 'short' in preference:
        return len(cleaned) <= 7 and syllables <= 2
    if '2 syllable' in preference:
        return 5 <= len(cleaned) <= 8 and syllables <= 3
    if '3 syllable' in preference:
        return len(cleaned) >= 6 and syllables >= 3
    return True


def has_awkward_original_shape(name):
    lowered = re.sub(r'[^a-z]', '', name.lower())
    if re.search(r'([aeiouy]{4,}|[^aeiouy]{4,})', lowered):
        return True
    if re.search(r'(.{2,3})\1', lowered):
        return True
    if lowered.endswith(('ii', 'ee', 'oo', 'yy')):
        return True
    if any(token in lowered for token in ['elleelle', 'iaia', 'aei', 'iaina', 'oai', 'aea', 'iai']):
        return True
    return False


def normalize_pronunciation(name):
    lowered = re.sub(r'[^a-z]', '', name.lower())
    if not lowered:
        return name.upper()

    chunks = re.findall(r'[^aeiouy]*[aeiouy]+(?:[^aeiouy](?=[^aeiouy])|[^aeiouy]?$)?', lowered)
    chunks = [chunk for chunk in chunks if chunk] or [lowered]

    def speak(chunk):
        replacements = [
            ('elle', 'ell'),
            ('ara', 'ahr-uh'),
            ('aire', 'air'),
            ('eau', 'oh'),
            ('que', 'k'),
            ('gue', 'g'),
            ('ai', 'ay'),
            ('ae', 'ay'),
            ('ea', 'ee-uh'),
            ('ia', 'ee-uh'),
            ('io', 'ee-oh'),
            ('ie', 'ee'),
            ('ei', 'ay'),
            ('ou', 'oo'),
            ('au', 'aw'),
            ('y', 'ee'),
        ]
        spoken = chunk
        for source, target in replacements:
            if source in spoken:
                spoken = spoken.replace(source, target)
                break
        if spoken.endswith('e') and len(spoken) > 2 and not spoken.endswith(('ee', 'ye')):
            spoken = spoken[:-1]
        if spoken.endswith('a'):
            spoken = spoken[:-1] + 'uh'
        elif spoken.endswith('i'):
            spoken = spoken[:-1] + 'ee'
        elif spoken.endswith('o'):
            spoken = spoken[:-1] + 'oh'
        return spoken

    spoken_chunks = [speak(chunk).capitalize() for chunk in chunks]
    if len(spoken_chunks) > 1:
        spoken_chunks[1] = spoken_chunks[1].upper()
    return '-'.join(spoken_chunks)


def build_original_candidate(profile, seed_index):
    starts, middles, ends = build_original_name_parts(profile)
    start = starts[seed_index % len(starts)]
    middle = middles[(seed_index * 3 + 1) % len(middles)]
    end = ends[(seed_index * 5 + 2) % len(ends)]
    length_preference = (profile.get('length_preference') or '').lower()
    if 'short' in length_preference:
        parts = [start, end]
    elif '3 syllable' in length_preference:
        parts = [start, middle, end]
    elif seed_index % 2:
        parts = [start, end]
    else:
        parts = [start, middle]
    name = stitch_name_parts(parts)
    name = re.sub(r'(.)\1{2,}', r'\1\1', name)
    name = name[:1].upper() + name[1:]
    return {
        'name': name,
        'pronunciation': normalize_pronunciation(name),
    }


def stitch_name_parts(parts):
    cleaned_parts = [str(part).strip() for part in parts if str(part).strip()]
    name = cleaned_parts[0] if cleaned_parts else ''
    for part in cleaned_parts[1:]:
        if not name:
            name = part
            continue
        if name[-1].lower() in 'aeiouy' and part[0].lower() in 'aeiouy':
            if name[-1].lower() == part[0].lower():
                part = part[1:]
            elif len(part) > 1:
                part = part[1:]
        name += part
    return name


def is_bad_original_candidate(name, known_names, previous_names):
    lowered = name.lower()
    if re.search(r'[^a-z]', lowered):
        return True
    if len(lowered) < 4 or len(lowered) > 10:
        return True
    if lowered in known_names:
        return True
    if lowered in {item.lower() for item in previous_names}:
        return True
    if any(token in lowered for token in ['xq', 'qz', 'zx', 'drug', 'tech', 'app']):
        return True
    if any(marker in lowered for marker in ['zyph', 'meloq', 'trilix']):
        return True
    if has_awkward_original_shape(name):
        return True
    return False


def score_original_candidate(name, form_data, known_names):
    lowered = re.sub(r'[^a-z]', '', name.lower())
    score = 100
    length_preference = form_data.get('length_preference') or ''
    if not fits_length_preference(lowered, length_preference):
        score -= 35
    if len(lowered) < 5 or len(lowered) > 9:
        score -= 12
    if syllable_count(lowered) > 4:
        score -= 20
    score += sayability_score(lowered, form_data)
    score += business_style_score(lowered, form_data)
    if any(slug_similarity(lowered, known) > 0.78 for known in known_names):
        score -= 8
    if any(marker in lowered for marker in FANTASY_OR_APP_ORIGINAL_MARKERS):
        score -= 14
    if lowered.endswith(('lor', 'lix', 'ian', 'q')):
        score -= 12
    avoid = (form_data.get('avoid_feel') or '').lower()
    if 'trendy' in avoid and any(token in lowered for token in ['lyn', 'leigh', 'den', 'son', 'xton']):
        score -= 18
    if 'fantasy' in avoid and any(token in lowered for token in ['x', 'z', 'ae', 'iel']):
        score -= 18
    if 'hard to say' in avoid and syllable_count(lowered) > 3:
        score -= 15
    return score


def build_original_style_line(form_data, tune_direction=''):
    tune_label = ORIGINAL_TUNE_LABELS.get(tune_direction, tune_direction.replace('_', ' ')) if tune_direction else ''
    pieces = [item for item in [form_data.get('style'), form_data.get('vibe'), form_data.get('market_position'), form_data.get('cultural_context'), tune_label] if item]
    return ', '.join(pieces) if pieces else 'Distinctive, usable, original'


def format_cultural_feel_phrase(cultural_feel):
    cleaned = (cultural_feel or '').strip().lower()
    if not cleaned:
        return ''
    article = 'an' if cleaned[0] in 'aeiou' else 'a'
    return f"{article} {cleaned} inspiration"


def build_original_fit_note(name, form_data, tune_direction=''):
    style = form_data.get('style') or 'balanced'
    vibe = form_data.get('vibe') or 'thoughtful'
    market_position = form_data.get('market_position')
    industry = form_data.get('industry')
    starting_letter = (form_data.get('starting_letter') or '').strip().upper()
    note = f"{name} was shaped to feel {style.lower()} and {vibe.lower()}."
    if industry:
        note += f" It is tuned for {industry.lower()}."
    if market_position:
        note += f" It keeps a {market_position.lower()} market feel in view."
    if form_data.get('cultural_context'):
        note += f" It leans toward {format_cultural_feel_phrase(form_data['cultural_context'])}."
    if starting_letter:
        note += f" It honors your request to begin with {starting_letter}."
    if tune_direction:
        tune_label = ORIGINAL_TUNE_LABELS.get(tune_direction, tune_direction.replace('_', ' '))
        note += f" This version leans {tune_label.lower()}."
    return note


def build_originality_note(name, known_names):
    close_matches = [known for known in known_names if slug_similarity(name, known) > 0.72][:2]
    if close_matches:
        return f"Low-match against checked name lists; closest echoes were screened against {', '.join(close_matches)}."
    return 'No close match found in the checked name lists.'


def generate_original_names_with_openai(form_data, tune_direction='', previous_names=None, reaction_note=''):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key or OpenAI is None:
        return None

    previous_names = previous_names or []
    known_names = original_known_names()
    try:
        client = OpenAI(api_key=api_key)
        details = build_original_details(
            form_data,
            tune_direction=tune_direction,
            previous_names=previous_names,
            reaction_note=reaction_note,
        )
        response = client.responses.create(
            model=os.getenv('OPENAI_ORIGINAL_MODEL', os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')),
            input=ORIGINAL_PROMPT_TEMPLATE.format(details=details),
            text={"format": {"type": "json_schema", "name": "original_names", "schema": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "pronunciation": {"type": "string"},
                                "style": {"type": "string"},
                                "structure": {"type": "string"},
                                "emotional_opener": {"type": "string"},
                                "why": {"type": "string"},
                                "fit_note": {"type": "string"},
                                "originality_note": {"type": "string"}
                            },
                            "required": ["name", "pronunciation", "style", "structure", "emotional_opener", "why", "fit_note", "originality_note"],
                            "additionalProperties": False
                        },
                        "minItems": 5,
                        "maxItems": 5
                    }
                },
                "required": ["names"],
                "additionalProperties": False
            }}}
        )
        raw_text = getattr(response, 'output_text', '') or ''
        payload = json.loads(raw_text) if raw_text else {}
        names = payload.get('names', []) if isinstance(payload, dict) else []
        accepted_names = []
        for item in names:
            if not is_acceptable_model_original(item, form_data, known_names, previous_names, accepted_names):
                continue
            accepted_names.append(item)
        if accepted_names:
            if len(accepted_names) < 5:
                fill_names = generate_original_fallback_names(
                    form_data,
                    tune_direction=tune_direction,
                    previous_names=[*previous_names, *(item['name'] for item in accepted_names)],
                )
                accepted_names.extend(fill_names[:5 - len(accepted_names)])
            accepted_names = accepted_names[:5]
            for index, item in enumerate(accepted_names):
                item['highlight'] = index == 0
            return accepted_names
        app.logger.warning('OpenAI original response did not pass quality gate. Raw text: %s', raw_text)
    except Exception as exc:
        app.logger.exception('OpenAI original generation failed: %s', exc)

    return None


def original_known_names():
    names = {item['name'].lower() for item in FALLBACK_NAMES}
    names.update({
        'olivia', 'emma', 'ava', 'amelia', 'charlotte', 'liam', 'noah', 'oliver', 'james', 'elijah',
        'sophia', 'isabella', 'mia', 'lucas', 'henry', 'theodore', 'liora', 'lucien', 'marcel',
        'rene', 'etienne', 'sebastien', 'bastien', 'mizuki', 'saira', 'elona',
        'arthur', 'august', 'beau', 'clement', 'emile', 'felix', 'hugo', 'jules', 'julien', 'leo',
        'louis', 'marceau', 'matteo', 'maxime', 'nicolas', 'remy', 'romain', 'sacha', 'theo',
        'aiko', 'akira', 'haru', 'haruki', 'hiro', 'kaia', 'kai', 'kenji', 'ren', 'riku', 'rinku',
        'sora', 'yuki', 'aoife', 'ciara', 'fiona', 'maeve', 'nia', 'nora', 'orin', 'rowan',
        'liora', 'elara', 'vela', 'lenora', 'mariel', 'avina', 'seline', 'mirel', 'sena',
        'renel', 'marcelin', 'jorel', 'albanis',
    })
    return names


def is_acceptable_model_original(item, form_data, known_names, previous_names, accepted_names):
    name = (item.get('name') or '').strip()
    lowered = name.lower()
    required_fields = ['name', 'pronunciation', 'style', 'structure', 'why', 'fit_note', 'originality_note']
    if any(not (item.get(field) or '').strip() for field in required_fields):
        return False
    if is_bad_original_candidate(lowered, known_names, previous_names):
        return False
    originality_note = (item.get('originality_note') or '').lower()
    if any(token in originality_note for token in ['moderate recognizability', 'recognizable', 'commonly used', 'established name', 'mythological']):
        return False
    if not fits_length_preference(lowered, form_data.get('length_preference')):
        return False
    if any(slug_similarity(lowered, existing['name']) > 0.86 for existing in accepted_names):
        return False
    return True


def generate_original_fallback_names(form_data, tune_direction='', previous_names=None):
    previous_names = previous_names or []
    tuned_form_data = {**form_data, 'tune_direction': tune_direction}
    known_names = original_known_names()

    candidates = []
    for seed_index in range(140):
        candidate = build_original_candidate(tuned_form_data, seed_index + len(previous_names))
        if is_bad_original_candidate(candidate['name'], known_names, previous_names):
            continue
        if any(slug_similarity(candidate['name'], existing['name']) > 0.86 for existing in candidates):
            continue
        candidate['_score'] = score_original_candidate(candidate['name'], form_data, known_names)
        candidate['style'] = build_original_style_line(form_data, tune_direction)
        candidate['structure'] = form_data.get('length_preference') or 'Balanced length'
        candidate['emotional_opener'] = infer_original_emotional_opener(candidate, form_data)
        candidate['why'] = f"An original name with a {candidate['style'].lower()} feel and an easy spoken shape."
        candidate['fit_note'] = build_original_fit_note(candidate['name'], form_data, tune_direction)
        candidate['originality_note'] = build_originality_note(candidate['name'], known_names)
        candidates.append(candidate)
        if len(candidates) >= 24:
            break

    candidates = sorted(candidates, key=lambda item: item['_score'], reverse=True)[:5]
    for index, candidate in enumerate(candidates):
        candidate.pop('_score', None)
        candidate['highlight'] = index == 0

    if len(candidates) < 5:
        while len(candidates) < 5:
            fallback_name = f"Orin{chr(97 + len(candidates))}"
            candidates.append({
                'name': fallback_name,
                'pronunciation': normalize_pronunciation(fallback_name),
                'style': build_original_style_line(form_data, tune_direction),
                'structure': form_data.get('length_preference') or 'Balanced length',
                'emotional_opener': 'Invented, but believable.',
                'why': 'An original fallback with a polished, usable structure.',
                'fit_note': build_original_fit_note(fallback_name, form_data, tune_direction),
                'originality_note': 'Screened as low-match against checked name lists.',
                'highlight': len(candidates) == 0,
            })

    return candidates


def enrich_original_names(names, form_data=None):
    form_data = form_data or {}
    enriched_names = []
    used_slugs = set()
    for index, item in enumerate(names, start=1):
        enriched = dict(item)
        base_slug = slugify_name(enriched['name'])
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        enriched['slug'] = slug
        enriched['rank_label'] = f"Original {index}"
        enriched['emotional_opener'] = clean_emotional_opener(
            enriched.get('emotional_opener') or infer_original_emotional_opener(enriched, form_data)
        )
        enriched['domain_info'] = build_domain_info(enriched['name'])
        enriched_names.append(enriched)
    return attach_domain_availability(enriched_names)


def generate_original_names(form_data, tune_direction='', previous_names=None, reaction_note=''):
    previous_names = previous_names or []
    names = generate_original_names_with_openai(
        form_data,
        tune_direction=tune_direction,
        previous_names=previous_names,
        reaction_note=reaction_note,
    )
    if names:
        return enrich_original_names(names, form_data)
    return enrich_original_names(generate_original_fallback_names(form_data, tune_direction=tune_direction, previous_names=previous_names), form_data)


def build_original_payload(form_data, tune_direction='', previous_names=None, tune_history=None, reactions=None):
    previous_names = previous_names or []
    tune_history = tune_history or []
    reactions = reactions or {}
    previous_name_items = [
        {'name': item['name'], 'slug': item.get('slug') or slugify_name(item['name'])}
        if isinstance(item, dict)
        else {'name': item, 'slug': slugify_name(item)}
        for item in previous_names
    ]
    reaction_note = build_reaction_summary(previous_name_items, reactions) if reactions and previous_name_items else ''
    names = generate_original_names(
        form_data,
        tune_direction=tune_direction,
        previous_names=[item['name'] for item in previous_name_items],
        reaction_note=reaction_note,
    )
    updated_history = [*tune_history, tune_direction] if tune_direction else list(tune_history)
    payload = {
        'form_data': form_data,
        'names': names,
        'original_summary': summarize_original_preferences(form_data, tune_direction=tune_direction),
        'editorial_note': build_original_editor_note(form_data, tune_direction=tune_direction),
        'brief_link': f"{url_for('original_name')}?{urlencode(form_data)}#original-brief" if any(form_data.values()) else f"{url_for('original_name')}#original-brief",
        'tune_options': ORIGINAL_TUNE_OPTIONS,
        'tune_direction': tune_direction,
        'tune_history': updated_history,
        'tune_chips': [item.replace('_', ' ').title() for item in updated_history[-3:]] or ['First pass'],
        'previous_names': [item['name'] for item in previous_name_items] + [item['name'] for item in names],
        'reaction_options': PRIMARY_REACTION_OPTIONS,
        'reactions': reactions,
        'can_react': not bool(updated_history),
    }
    share_id = create_original_share_snapshot(payload)
    payload['share_id'] = share_id
    payload['share_path'] = url_for('shared_shortlist', share_id=share_id)
    payload['share_url'] = absolute_url(payload['share_path'])
    payload['share_message'] = build_original_share_message(payload)
    payload['powered_by'] = 'Powered by NamEngine Business'
    return payload


def generate_shortlist_payload(form_data, *, refinement_note='', prior_reactions=None, exclude_names=None, round_number=1, parent_shortlist_id=None):
    raw_names, used_fallback = generate_names(form_data, refinement_note=refinement_note, exclude_names=exclude_names)
    names = enrich_names(raw_names, form_data)
    reactions = prior_reactions or {}
    completed, total = reaction_progress(names, reactions)
    next_actions = build_next_actions(round_number)
    shortlist = {
        'names': names,
        'used_fallback': used_fallback,
        'preference_summary': summarize_preferences(form_data),
        'editor_note': build_editor_note(form_data, used_fallback, round_number=round_number),
        'refine_link': build_refine_link(form_data),
        'start_over_link': '/#brief',
        'form_data': form_data,
        'intake_dimensions': infer_dimensions(form_data),
        'reaction_options': PRIMARY_REACTION_OPTIONS,
        'reactions': reactions,
        'reaction_summary': build_reaction_summary(names, reactions) if reactions else '',
        'reaction_effect_note': '',
        'taste_profile': infer_taste_profile(form_data, reactions, names) if reactions else '',
        'taste_summary_note': build_taste_summary_note(form_data, reactions, names) if reactions else '',
        'reaction_progress_label': f"{completed} of {total} reactions",
        'has_enough_reactions': len(reactions) >= 3,
        'round_number': round_number,
        'round_label': make_round_label(round_number),
        'is_refined_round': round_number > 1,
        'parent_shortlist_id': parent_shortlist_id,
        **next_actions,
    }
    shortlist['shortlist_id'] = store_shortlist(shortlist)
    shortlist['ancestry_shortlist_ids'] = ancestry_shortlist_ids(shortlist)
    share_id = create_share_snapshot(shortlist)
    shortlist['share_id'] = share_id
    shortlist['share_path'] = url_for('shared_shortlist', share_id=share_id)
    shortlist['share_url'] = absolute_url(shortlist['share_path'])
    shortlist['share_message'] = build_share_message(shortlist)
    shortlist['powered_by'] = 'Powered by NamEngine Business'
    return shortlist


def get_shortlist_or_404(shortlist_id):
    shortlist = SHORTLIST_STORE.get(shortlist_id)
    if not shortlist:
        abort(404)
    return shortlist


@app.route('/', methods=['GET'])
def home():
    form_data = normalized_form_data(request.args)
    homepage_meta_image = absolute_url(url_for('static', filename='images/namengine-business-card-share-v2.jpg'))
    homepage_url = absolute_url(url_for('home'))
    return render_template(
        'index.html',
        form_data=form_data,
        homepage_meta_image=homepage_meta_image,
        homepage_url=homepage_url,
    )


@app.route('/original', methods=['GET'])
def original_name():
    form_data = normalized_form_data(request.args, defaults=ORIGINAL_FORM_DATA)
    return render_template('original_index.html', form_data=form_data)


@app.route('/results', methods=['GET', 'POST'])
def results():
    if request.method == 'GET' and request.args.get('shortlist'):
        shortlist = get_shortlist_or_404(request.args['shortlist'])
        return render_template('results.html', **shortlist)

    source = request.form if request.method == 'POST' else request.args
    form_data = normalized_form_data(source)
    shortlist = generate_shortlist_payload(form_data, round_number=1)
    return render_template('results.html', **shortlist)


@app.route('/results/refine', methods=['POST'])
def refine_results():
    form_data = normalized_form_data(request.form)
    prior_shortlist_id = request.form.get('shortlist_id', '')
    prior_shortlist = get_shortlist_or_404(prior_shortlist_id)
    if not prior_shortlist.get('can_refine', True):
        return render_template('results.html', **prior_shortlist)

    reactions = parse_reactions(request.form)
    next_round_number = prior_shortlist.get('round_number', 1) + 1
    refinement_note = build_refinement_note(form_data, reactions, prior_shortlist['names'], next_round_number)
    exclude_names = collect_seen_names(prior_shortlist)
    shortlist = generate_shortlist_payload(
        form_data,
        refinement_note=refinement_note,
        prior_reactions=reactions,
        exclude_names=exclude_names,
        round_number=next_round_number,
        parent_shortlist_id=prior_shortlist_id,
    )
    shortlist['reaction_summary'] = build_reaction_summary(prior_shortlist['names'], reactions)
    shortlist['reaction_effect_note'] = build_reaction_effect_note(prior_shortlist['names'], reactions)
    shortlist['taste_profile'] = infer_taste_profile(form_data, reactions, prior_shortlist['names'])
    shortlist['taste_summary_note'] = build_taste_summary_note(form_data, reactions, prior_shortlist['names'])
    shortlist['prior_shortlist_id'] = prior_shortlist_id
    share_id = create_share_snapshot(shortlist)
    shortlist['share_id'] = share_id
    shortlist['share_path'] = url_for('shared_shortlist', share_id=share_id)
    shortlist['share_url'] = absolute_url(shortlist['share_path'])
    shortlist['share_message'] = build_share_message(shortlist)
    shortlist['powered_by'] = 'Powered by NamEngine Business'
    return render_template('results.html', **shortlist)


@app.route('/original/results', methods=['GET', 'POST'])
def original_results():
    source = request.form if request.method == 'POST' else request.args
    form_data = normalized_form_data(source, defaults=ORIGINAL_FORM_DATA)
    tune_direction = (source.get('tune_direction', '') if source else '').strip().lower().replace(' ', '_')
    if tune_direction not in ORIGINAL_TUNE_LABELS:
        tune_direction = ''
    previous_names = parse_history_field(source.get('previous_names', '') if source else '')
    tune_history = parse_history_field(source.get('tune_history', '') if source else '')
    reactions = parse_reactions(source)
    payload = build_original_payload(
        form_data,
        tune_direction=tune_direction,
        previous_names=previous_names,
        tune_history=tune_history,
        reactions=reactions,
    )
    return render_template('original_results.html', **payload)


@app.route('/share/<share_id>', methods=['GET'])
def shared_shortlist(share_id):
    payload = get_share_payload_or_404(share_id)
    payload = dict(payload)
    payload['share_id'] = share_id
    payload['share_url'] = request.url
    payload['powered_by'] = payload.get('powered_by', 'Powered by NamEngine Business')

    if payload.get('mode') == 'original':
        payload.update(build_share_meta(payload, mode='original'))
        payload['brief_link'] = f"{url_for('original_name')}?{urlencode(payload.get('form_data', {}))}#original-brief" if payload.get('form_data') else f"{url_for('original_name')}#original-brief"
        payload['tune_options'] = []
        payload['tune_history'] = payload.get('tune_history', [])
        payload['tune_chips'] = [item.replace('_', ' ').title() for item in payload.get('tune_history', [])[-3:]] or ['Shared set']
        payload['previous_names'] = [item['name'] for item in payload.get('names', [])]
        payload['share_message'] = payload.get('shared_message', build_original_share_message(payload))
        return render_template('original_results.html', **payload)

    payload.update(build_share_meta(payload, mode='shortlist'))
    payload['start_over_link'] = '/#brief'
    payload['refine_link'] = build_refine_link(payload.get('form_data', {}))
    return render_template('shared_shortlist.html', **payload)


@app.route('/choose', methods=['POST'])
def choose_name():
    source_share_id = request.form.get('share_id', '').strip()
    slug = request.form.get('slug', '').strip()
    if not source_share_id or not slug:
        abort(400)
    chosen_id = create_chosen_name_snapshot(source_share_id, slug)
    return redirect(url_for('chosen_name', chosen_id=chosen_id))


@app.route('/chosen/<chosen_id>', methods=['GET'])
def chosen_name(chosen_id):
    payload = dict(get_share_payload_or_404(chosen_id))
    if payload.get('mode') != 'chosen':
        abort(404)
    payload['chosen_id'] = chosen_id
    payload['share_url'] = request.url
    payload['share_message'] = payload.get('shared_message', build_chosen_share_message(payload))
    payload['source_link'] = url_for('shared_shortlist', share_id=payload['source_share_id']) if payload.get('source_share_id') else url_for('home')
    payload['start_over_link'] = '/#brief'
    payload.update(build_chosen_share_meta(payload))
    return render_template('chosen_name.html', **payload)


@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if not feedback_enabled():
        abort(404)

    submitted = False
    form_data = {
        'name': '',
        'email': '',
        'tester_type': '',
        'overall_rating': '',
        'used_original': '',
        'would_share': '',
        'liked_most': '',
        'confusing': '',
        'missing': '',
        'bug': '',
        'other_notes': '',
        'page_url': '',
    }
    if request.method == 'POST':
        form_data.update({key: request.form.get(key, '') for key in form_data})
        store_feedback(request.form)
        submitted = True
        form_data = {key: '' for key in form_data}
    return render_template(
        'feedback.html',
        form_data=form_data,
        submitted=submitted,
        admin_link=build_feedback_admin_link(),
    )


@app.route('/feedback/responses', methods=['GET'])
def feedback_responses():
    if not feedback_admin_allowed():
        abort(404)
    entries = sorted(load_feedback_store(), key=lambda item: item.get('created_at', ''), reverse=True)
    return render_template('feedback_responses.html', entries=entries)


@app.route('/name/<slug>', methods=['GET'])
def name_detail(slug):
    shortlist_id = request.args.get('shortlist', '')
    shortlist = get_shortlist_or_404(shortlist_id)
    names = shortlist['names']
    selected = next((item for item in names if item['slug'] == slug), None)
    if not selected:
        abort(404)

    return render_template(
        'name_detail.html',
        name=selected,
        names=names,
        form_data=shortlist['form_data'],
        detail_profile=build_detail_profile(selected, names, shortlist['form_data']),
        preference_summary=shortlist['preference_summary'],
        refine_link=shortlist['refine_link'],
        start_over_link=shortlist.get('start_over_link', '/#brief'),
        used_fallback=shortlist['used_fallback'],
        shortlist_id=shortlist_id,
        share_id=shortlist.get('share_id', ''),
        round_label=shortlist.get('round_label', make_round_label(1)),
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)



