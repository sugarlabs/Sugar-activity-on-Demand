# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-activity icons.

The model that wrote the activity also draws its icon: one small
``generate_text`` call returns a 55x55 Sugar-style SVG built on
Sugar's ``&stroke_color;``/``&fill_color;`` entities, so every icon
is specific to the idea ("space racer" gets a rocket, not a category
glyph) and still recolors to the learner's XO colors.  The reply is
strictly sanitized; anything doubtful falls back to the deterministic
template/category glyph below, which never fails.
"""

import hashlib
import logging
import os
import re

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
    '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" [\n'
    '  <!ENTITY stroke_color "#282828">\n'
    '  <!ENTITY fill_color "#FFFFFF">\n'
    ']>\n'
)

_TEMPLATE = _HEADER + (
    '<svg xmlns="http://www.w3.org/2000/svg" width="55" height="55" '
    'viewBox="0 0 55 55">\n'
    '  <g transform="rotate(%(angle)d 27.5 27.5)">\n'
    '%(glyph)s'
    '  </g>\n'
    '  <circle cx="%(accent_x)d" cy="%(accent_y)d" r="3" '
    'fill="&stroke_color;"/>\n'
    '</svg>\n'
)

_S = 'stroke="&stroke_color;"'
_F = 'fill="&fill_color;"'
_SF = _S + ' ' + _F

_GLYPHS = {
    'quiz': (
        '    <rect x="12" y="10" width="31" height="35" rx="4" '
        + _SF + ' stroke-width="3"/>\n'
        '    <path d="M21 22 q0-6 6.5-6 q6.5 0 6.5 6 q0 5 -6.5 7 l0 3" '
        'fill="none" ' + _S + ' stroke-width="3.5" '
        'stroke-linecap="round"/>\n'
        '    <circle cx="27.5" cy="38" r="2.5" fill="&stroke_color;"/>\n'
    ),
    'grid': (
        '    <rect x="10" y="10" width="15" height="15" rx="2" '
        + _SF + ' stroke-width="3"/>\n'
        '    <rect x="30" y="10" width="15" height="15" rx="2" '
        + _SF + ' stroke-width="3"/>\n'
        '    <rect x="10" y="30" width="15" height="15" rx="2" '
        + _SF + ' stroke-width="3"/>\n'
        '    <rect x="30" y="30" width="15" height="15" rx="2" '
        'fill="&stroke_color;" ' + _S + ' stroke-width="3"/>\n'
    ),
    'canvas': (
        '    <path d="M12 40 Q20 20 30 28 Q42 38 44 14" fill="none" '
        + _S + ' stroke-width="4.5" stroke-linecap="round"/>\n'
        '    <circle cx="14" cy="42" r="5" ' + _SF
        + ' stroke-width="3"/>\n'
    ),
    'narrative': (
        '    <path d="M27.5 14 Q18 9 9 13 L9 41 Q18 37 27.5 42 '
        'Q37 37 46 41 L46 13 Q37 9 27.5 14 Z" '
        + _SF + ' stroke-width="3"/>\n'
        '    <path d="M27.5 14 L27.5 42" fill="none" '
        + _S + ' stroke-width="3"/>\n'
    ),
    'utility': (
        '    <circle cx="27.5" cy="27.5" r="10" ' + _SF
        + ' stroke-width="3.5"/>\n'
        '    <path d="M27.5 9 V17 M27.5 38 V46 M9 27.5 H17 '
        'M38 27.5 H46 M14.5 14.5 L20 20 M35 35 L40.5 40.5 '
        'M40.5 14.5 L35 20 M20 35 L14.5 40.5" fill="none" '
        + _S + ' stroke-width="3.5" stroke-linecap="round"/>\n'
    ),
    'chess': (
        '    <path d="M17 45 L38 45 L36 32 L40 20 L34 20 L34 24 '
        'L30 24 L30 20 L25 20 L25 24 L21 24 L21 20 L15 20 L19 32 Z" '
        + _SF + ' stroke-width="3" stroke-linejoin="round"/>\n'
    ),
    'carrom': (
        '    <circle cx="24" cy="31" r="12" ' + _SF
        + ' stroke-width="3.5"/>\n'
        '    <circle cx="38" cy="16" r="6" fill="&stroke_color;" '
        + _S + ' stroke-width="2"/>\n'
    ),
    'science': (
        '    <path d="M23 10 L23 24 L13 42 Q11 46 16 46 L39 46 '
        'Q44 46 42 42 L32 24 L32 10 Z" '
        + _SF + ' stroke-width="3" stroke-linejoin="round"/>\n'
        '    <path d="M20 10 L35 10" fill="none" ' + _S
        + ' stroke-width="3" stroke-linecap="round"/>\n'
        '    <circle cx="24" cy="38" r="2.5" fill="&stroke_color;"/>\n'
    ),
    'language': (
        '    <path d="M10 12 H45 V36 H26 L16 45 L18 36 H10 Z" '
        + _SF + ' stroke-width="3" stroke-linejoin="round"/>\n'
        '    <path d="M17 21 H38 M17 28 H32" fill="none" '
        + _S + ' stroke-width="3" stroke-linecap="round"/>\n'
    ),
    'games': (
        '    <circle cx="27.5" cy="27.5" r="18" ' + _SF
        + ' stroke-width="3.5"/>\n'
        '    <path d="M23 19 L37 27.5 L23 36 Z" '
        'fill="&stroke_color;"/>\n'
    ),
    'rocket': (
        '    <path d="M27.5 8 C34 14 36 26 33 36 L22 36 C19 26 21 14 '
        '27.5 8 Z" ' + _SF + ' stroke-width="3" '
        'stroke-linejoin="round"/>\n'
        '    <circle cx="27.5" cy="22" r="3.5" fill="&stroke_color;"/>\n'
        '    <path d="M22 34 L15 45 L23 40 M33 34 L40 45 L32 40" '
        'fill="none" ' + _S + ' stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
    ),
    'star': (
        '    <path d="M27.5 8 L33 22 L48 22 L36 31 L41 46 L27.5 37 '
        'L14 46 L19 31 L7 22 L22 22 Z" ' + _SF + ' stroke-width="3" '
        'stroke-linejoin="round"/>\n'
    ),
    'flower': (
        '    <circle cx="27.5" cy="15" r="7" ' + _SF
        + ' stroke-width="2.5"/>\n'
        '    <circle cx="40" cy="27.5" r="7" ' + _SF
        + ' stroke-width="2.5"/>\n'
        '    <circle cx="27.5" cy="40" r="7" ' + _SF
        + ' stroke-width="2.5"/>\n'
        '    <circle cx="15" cy="27.5" r="7" ' + _SF
        + ' stroke-width="2.5"/>\n'
        '    <circle cx="27.5" cy="27.5" r="6" fill="&stroke_color;" '
        + _S + ' stroke-width="2"/>\n'
    ),
    'clock': (
        '    <circle cx="27.5" cy="27.5" r="18" ' + _SF
        + ' stroke-width="3.5"/>\n'
        '    <path d="M27.5 27.5 L27.5 15 M27.5 27.5 L37 31" '
        'fill="none" ' + _S + ' stroke-width="3" '
        'stroke-linecap="round"/>\n'
    ),
    'music': (
        '    <path d="M22 12 L38 9 L38 34" fill="none" ' + _S
        + ' stroke-width="3" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
        '    <circle cx="17" cy="36" r="6" fill="&stroke_color;" '
        + _S + ' stroke-width="2"/>\n'
        '    <circle cx="33" cy="38" r="6" fill="&stroke_color;" '
        + _S + ' stroke-width="2"/>\n'
    ),
    'heart': (
        '    <path d="M27.5 45 C10 32 12 16 22 16 C27 16 27.5 21 27.5 21 '
        'C27.5 21 28 16 33 16 C43 16 45 32 27.5 45 Z" ' + _SF
        + ' stroke-width="3" stroke-linejoin="round"/>\n'
    ),
    'default': (
        '    <circle cx="27.5" cy="27.5" r="18" ' + _SF
        + ' stroke-width="3.5"/>\n'
        '    <path d="M18 28 L25 35 L38 20" fill="none" '
        + _S + ' stroke-width="4" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
    ),
}

# Concept keywords that pick a glyph for what the activity is ABOUT, before
# falling back to the template/category glyph.  Matched against whole words in
# the name, summary, and word bank so "start" never trips "star".
_KEYWORD_GLYPHS = (
    (frozenset({'rocket', 'space', 'planet', 'planets', 'astronaut',
                'galaxy', 'spaceship', 'orbit'}), 'rocket'),
    (frozenset({'star', 'stars', 'constellation'}), 'star'),
    (frozenset({'flower', 'flowers', 'garden', 'plant', 'plants', 'petal',
                'bloom', 'seed', 'seeds'}), 'flower'),
    (frozenset({'clock', 'time', 'timer', 'hour', 'hours', 'minute',
                'minutes', 'schedule'}), 'clock'),
    (frozenset({'music', 'song', 'songs', 'melody', 'note', 'notes',
                'rhythm', 'piano'}), 'music'),
    (frozenset({'heart', 'hearts', 'health', 'feeling', 'feelings',
                'emotion', 'emotions'}), 'heart'),
)

_CATEGORY_GLYPHS = {
    'science': 'science',
    'language': 'language',
    'games': 'games',
    'logic_math': 'grid',
    'tools_utils': 'utility',
    'creation': 'canvas',
}

_ACCENTS = ((46, 8), (46, 46), (8, 46), (8, 8))


def _concept_glyph(plan):
    """Return a concept glyph key from the plan's words, or None."""
    haystack = ' '.join((
        str(plan.get('name') or ''),
        str(plan.get('summary') or ''),
        ' '.join(str(word) for word in (plan.get('word_bank') or ())),
    )).lower()
    tokens = set(re.findall(r'[a-z]+', haystack))
    for keywords, glyph in _KEYWORD_GLYPHS:
        if tokens & keywords:
            return glyph
    return None


def render_activity_icon(plan):
    """Return a Sugar-style SVG icon for this plan; never raises."""
    try:
        template = str(plan.get('template') or '')
        category = str(plan.get('category') or '')
        name = str(plan.get('name') or 'Activity')

        # Concept first (a "space race" gets a rocket, not a games glyph),
        # then the template glyph, then the category glyph, then default.
        glyph_key = _concept_glyph(plan)
        if glyph_key is None:
            if template in _GLYPHS:
                glyph_key = template
            elif category in _CATEGORY_GLYPHS:
                glyph_key = _CATEGORY_GLYPHS[category]
            else:
                glyph_key = 'default'

        digest = int(
            hashlib.sha256(name.encode('utf-8')).hexdigest()[:8], 16)
        accent_x, accent_y = _ACCENTS[digest % len(_ACCENTS)]
        angle = (digest // 7) % 13 - 6  # -6..6 degrees

        return _TEMPLATE % {
            'glyph': _GLYPHS[glyph_key],
            'angle': angle,
            'accent_x': accent_x,
            'accent_y': accent_y,
        }
    except Exception:
        return _TEMPLATE % {
            'glyph': _GLYPHS['default'],
            'angle': 0,
            'accent_x': 46,
            'accent_y': 8,
        }


_MAX_ICON_CHARS = 6000

_FORBIDDEN_MARKUP = (
    '<script', '<image', '<foreignobject', '<iframe', '<text',
    '<style', 'javascript:', '<lineargradient', '<radialgradient',
    '<filter', '<use', '<animate',
)

_EVENT_ATTR = re.compile(r'\bon[a-z]+\s*=', re.IGNORECASE)
_EXTERNAL_REF = re.compile(r'(?:xlink:)?href\s*=\s*["\'](?!#)')


def build_icon_system_prompt():
    return (
        'You draw icons for Sugar learning activities.\n\n'
        'Return ONLY an SVG document for a 55x55 icon of the activity '
        'described.  No explanations, no markdown fences.\n\n'
        'Rules:\n'
        '- The root element must be: <svg '
        'xmlns="http://www.w3.org/2000/svg" width="55" height="55" '
        'viewBox="0 0 55 55">\n'
        '- Draw with Sugar\'s color entities: stroke="&stroke_color;" '
        'for outlines, fill="&fill_color;" for filled shapes, and '
        'fill="&stroke_color;" for small solid accents.  Never use '
        'literal colors.\n'
        '- Bold and simple so it reads at small size: 2-6 shapes, '
        'stroke-width 3 to 4.5, stroke-linecap="round", '
        'stroke-linejoin="round".\n'
        '- Keep about 4 units of padding inside the edges.\n'
        '- Use only these elements: path, rect, circle, ellipse, '
        'line, polyline, polygon, g.  No text, gradients, filters, '
        'images, scripts, style blocks, or external references.\n'
        '- Draw ONE clear visual metaphor for what the learner does '
        'in this activity (a rocket for a space game, a flower for a '
        'garden counter).\n'
    )


def build_icon_user_prompt(spec, plan):
    parts = [
        'Draw the icon for this Sugar activity.\n',
        'Name: %s\n' % getattr(spec, 'name', ''),
    ]
    if isinstance(plan, dict):
        kind = plan.get('activity_kind') or ''
        summary = plan.get('summary') or ''
        goal = plan.get('learner_goal') or ''
        if kind:
            parts.append('What it is: %s\n' % kind)
        if summary:
            parts.append('Summary: %s\n' % summary)
        if goal:
            parts.append('What the learner does: %s\n' % goal)
        # The word bank names the concrete things in the activity, which are
        # exactly what a single clear visual metaphor should draw from.
        words = [
            str(word).strip() for word in (plan.get('word_bank') or ())
            if str(word).strip()
        ][:8]
        if words:
            parts.append('Key ideas to picture: %s\n' % ', '.join(words))
    parts.append('Learning area: %s\n' % getattr(spec, 'category', ''))
    parts.append(
        '\nPick the single most recognisable object from the ideas above and '
        'draw just that.\nReturn only the SVG.')
    return ''.join(parts)


def sanitize_icon_svg(text):
    """Return a safe, colorizable Sugar icon SVG, or None.

    Accepts raw model output (possibly fenced or wrapped in prose),
    extracts the <svg> element, rejects anything scriptable or
    externally referencing, requires Sugar's color entities and the
    55x55 viewBox, and re-heads the document with the canonical
    entity declaration so the icon parses everywhere Sugar loads it.
    """
    if not isinstance(text, str):
        return None

    start = text.find('<svg')
    end = text.find('</svg>', start)
    if start < 0 or end < 0:
        return None
    svg = text[start:end + len('</svg>')]

    if len(svg) > _MAX_ICON_CHARS:
        return None
    lowered = svg.lower()
    if any(marker in lowered for marker in _FORBIDDEN_MARKUP):
        return None
    if _EVENT_ATTR.search(svg) or _EXTERNAL_REF.search(svg):
        return None
    if 'viewBox="0 0 55 55"' not in svg:
        return None
    if '&stroke_color;' not in svg:
        return None

    candidate = _HEADER + svg + '\n'
    try:
        from xml.dom import minidom
        document = minidom.parseString(candidate)
        if document.documentElement.tagName != 'svg':
            return None
    except Exception:
        return None
    return candidate


_ICON_RETRY_HINT = (
    '\n\nYour previous drawing could not be used.  Return ONLY a single '
    '<svg xmlns="http://www.w3.org/2000/svg" width="55" height="55" '
    'viewBox="0 0 55 55"> ... </svg> document with no markdown fences and '
    'no prose.  Use only path, rect, circle, ellipse, line, polyline, '
    'polygon, and g elements.  Color strictly with &stroke_color; and '
    '&fill_color; — never literal colors, gradients, filters, text, '
    'images, or scripts.'
)


def _icon_attempts():
    """How many times to ask the model to draw before falling back."""
    try:
        value = int(os.environ.get('AOD_ICON_ATTEMPTS', '3'))
    except (TypeError, ValueError):
        value = 3
    return max(1, min(value, 5))


def request_icon_svg(provider, spec, plan):
    """Ask the model to draw this activity's icon; never raises.

    Every activity gets an AI-drawn icon when a drawing-capable provider is
    reachable.  The model is asked up to ``AOD_ICON_ATTEMPTS`` times (default
    3), because a first reply occasionally trips the SVG sanitizer (a stray
    gradient, a literal color, a markdown fence); each retry restates the
    constraints.  Returns a sanitized SVG string, or None when the feature is
    off, the provider cannot draw, or every attempt fails — only then does the
    caller fall back to the deterministic render_activity_icon() glyph.
    """
    if os.environ.get('AOD_AI_ICON', 'on').lower() in (
            'off', '0', 'no', 'false'):
        return None
    generate_text = getattr(provider, 'generate_text', None)
    if not callable(generate_text):
        return None

    system_prompt = build_icon_system_prompt()
    base_user_prompt = build_icon_user_prompt(spec, plan)
    attempts = _icon_attempts()

    for attempt in range(1, attempts + 1):
        user_prompt = base_user_prompt if attempt == 1 else (
            base_user_prompt + _ICON_RETRY_HINT)
        try:
            response = generate_text(system_prompt, user_prompt)
        except Exception as error:
            logging.warning('Icon drawing call failed (attempt %d/%d): %s',
                            attempt, attempts,
                            _redact_provider_value(error, provider))
            continue

        if _contains_provider_secret(response, provider):
            logging.warning('Model icon contained credential material')
            continue

        icon = sanitize_icon_svg(response)
        if icon is not None:
            return icon
        logging.warning('Model icon failed sanitization (attempt %d/%d)',
                        attempt, attempts)

    logging.warning('Model could not draw a usable icon after %d attempt(s); '
                    'using the deterministic fallback', attempts)
    return None


def _provider_secrets(provider):
    return [
        value for value in (
            getattr(provider, '_api_key', ''),
            getattr(provider, 'api_key', ''),
        )
        if isinstance(value, str) and value
    ]


def _contains_provider_secret(value, provider):
    return isinstance(value, str) and any(
        secret in value for secret in _provider_secrets(provider))


def _redact_provider_value(value, provider):
    text = str(value)
    for secret in _provider_secrets(provider):
        text = text.replace(secret, '[redacted]')
    return text
