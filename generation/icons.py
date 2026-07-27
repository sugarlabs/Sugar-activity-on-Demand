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
    'book': (
        '    <rect x="14" y="10" width="27" height="35" rx="3" '
        + _SF + ' stroke-width="3"/>\n'
        '    <path d="M20 10 L20 45" fill="none" ' + _S
        + ' stroke-width="3"/>\n'
        '    <path d="M26 19 H37 M26 26 H37 M26 33 H33" fill="none" '
        + _S + ' stroke-width="2.5" stroke-linecap="round"/>\n'
    ),
    'pencil': (
        '    <path d="M14 41 L16 33 L36 13 L42 19 L22 39 Z" '
        + _SF + ' stroke-width="3" stroke-linejoin="round"/>\n'
        '    <path d="M33 16 L39 22" fill="none" ' + _S
        + ' stroke-width="3"/>\n'
        '    <path d="M15 40 L21 38" fill="none" ' + _S
        + ' stroke-width="2.5" stroke-linecap="round"/>\n'
    ),
    'palette': (
        '    <path d="M27.5 10 C40 10 46 18 46 27 C46 33 41 34 37 34 '
        'C33 34 33 39 30 41 C28 42 27.5 43 25 43 C16 43 9 36 9 27 '
        'C9 17 16 10 27.5 10 Z" ' + _SF
        + ' stroke-width="3" stroke-linejoin="round"/>\n'
        '    <circle cx="20" cy="23" r="2.5" fill="&stroke_color;"/>\n'
        '    <circle cx="29" cy="18" r="2.5" fill="&stroke_color;"/>\n'
        '    <circle cx="37" cy="23" r="2.5" fill="&stroke_color;"/>\n'
    ),
    'globe': (
        '    <circle cx="27.5" cy="27.5" r="18" ' + _SF
        + ' stroke-width="3"/>\n'
        '    <path d="M9.5 27.5 H45.5 M27.5 9.5 V45.5" fill="none" '
        + _S + ' stroke-width="2"/>\n'
        '    <path d="M27.5 9.5 Q15 27.5 27.5 45.5 Q40 27.5 27.5 9.5" '
        'fill="none" ' + _S + ' stroke-width="2"/>\n'
    ),
    'leaf': (
        '    <path d="M13 42 Q13 15 42 13 Q40 42 13 42 Z" '
        + _SF + ' stroke-width="3" stroke-linejoin="round"/>\n'
        '    <path d="M14 41 Q27 28 40 20" fill="none" ' + _S
        + ' stroke-width="2.5" stroke-linecap="round"/>\n'
    ),
    'sun': (
        '    <circle cx="27.5" cy="27.5" r="9" ' + _SF
        + ' stroke-width="3"/>\n'
        '    <path d="M27.5 6 V13 M27.5 42 V49 M6 27.5 H13 M42 27.5 H49 '
        'M12 12 L17 17 M38 38 L43 43 M43 12 L38 17 M17 38 L12 43" '
        'fill="none" ' + _S + ' stroke-width="3" '
        'stroke-linecap="round"/>\n'
    ),
    'drop': (
        '    <path d="M27.5 8 C27.5 8 40 24 40 34 A12.5 12.5 0 0 1 15 34 '
        'C15 24 27.5 8 27.5 8 Z" ' + _SF
        + ' stroke-width="3" stroke-linejoin="round"/>\n'
        '    <path d="M22 34 A6 6 0 0 0 28 40" fill="none" ' + _S
        + ' stroke-width="2.5" stroke-linecap="round"/>\n'
    ),
    'paw': (
        '    <ellipse cx="27.5" cy="35" rx="10" ry="8" ' + _SF
        + ' stroke-width="3"/>\n'
        '    <circle cx="15" cy="25" r="4" ' + _SF
        + ' stroke-width="2.5"/>\n'
        '    <circle cx="23" cy="17" r="4" ' + _SF
        + ' stroke-width="2.5"/>\n'
        '    <circle cx="32" cy="17" r="4" ' + _SF
        + ' stroke-width="2.5"/>\n'
        '    <circle cx="40" cy="25" r="4" ' + _SF
        + ' stroke-width="2.5"/>\n'
    ),
    'ball': (
        '    <circle cx="27.5" cy="27.5" r="18" ' + _SF
        + ' stroke-width="3"/>\n'
        '    <path d="M27.5 17 L36 23 L33 34 L22 34 L19 23 Z" '
        'fill="&stroke_color;"/>\n'
        '    <path d="M27.5 9.5 V17 M36 23 L44 20 M33 34 L39 41 '
        'M22 34 L16 41 M19 23 L11 20" fill="none" ' + _S
        + ' stroke-width="2"/>\n'
    ),
    'dice': (
        '    <rect x="12" y="12" width="31" height="31" rx="5" '
        + _SF + ' stroke-width="3"/>\n'
        '    <circle cx="21" cy="21" r="2.5" fill="&stroke_color;"/>\n'
        '    <circle cx="34" cy="21" r="2.5" fill="&stroke_color;"/>\n'
        '    <circle cx="27.5" cy="27.5" r="2.5" fill="&stroke_color;"/>\n'
        '    <circle cx="21" cy="34" r="2.5" fill="&stroke_color;"/>\n'
        '    <circle cx="34" cy="34" r="2.5" fill="&stroke_color;"/>\n'
    ),
    'robot': (
        '    <rect x="14" y="18" width="27" height="24" rx="4" '
        + _SF + ' stroke-width="3"/>\n'
        '    <path d="M27.5 10 V18" fill="none" ' + _S
        + ' stroke-width="3"/>\n'
        '    <circle cx="27.5" cy="9" r="3" fill="&stroke_color;"/>\n'
        '    <circle cx="22" cy="28" r="3" fill="&stroke_color;"/>\n'
        '    <circle cx="33" cy="28" r="3" fill="&stroke_color;"/>\n'
        '    <path d="M22 36 H33" fill="none" ' + _S
        + ' stroke-width="2.5" stroke-linecap="round"/>\n'
    ),
    # The universal fallback: a lightbulb, because every activity starts as
    # an idea.  Friendlier and more on-theme than a bare checkmark.
    'default': (
        '    <path d="M27.5 8 A14 14 0 0 1 36 33 Q33 36 33 40 L22 40 '
        'Q22 36 19 33 A14 14 0 0 1 27.5 8 Z" ' + _SF
        + ' stroke-width="3" stroke-linejoin="round"/>\n'
        '    <path d="M23 44 H32 M25 47 H30" fill="none" ' + _S
        + ' stroke-width="2.5" stroke-linecap="round"/>\n'
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
    (frozenset({'read', 'reading', 'book', 'books', 'library',
                'chapter', 'novel'}), 'book'),
    (frozenset({'write', 'writing', 'writer', 'spell', 'spelling',
                'handwriting', 'essay', 'sentence', 'sentences'}), 'pencil'),
    (frozenset({'paint', 'painting', 'art', 'artist', 'palette',
                'colour', 'colours', 'color', 'colors'}), 'palette'),
    (frozenset({'globe', 'world', 'earth', 'map', 'maps', 'geography',
                'country', 'countries', 'continent', 'continents'}), 'globe'),
    (frozenset({'tree', 'trees', 'leaf', 'leaves', 'forest', 'nature',
                'jungle', 'woods'}), 'leaf'),
    (frozenset({'sun', 'sunny', 'weather', 'sky', 'summer', 'sunshine',
                'daylight'}), 'sun'),
    (frozenset({'water', 'rain', 'ocean', 'sea', 'river', 'lake',
                'drop', 'droplet', 'wave', 'waves'}), 'drop'),
    (frozenset({'animal', 'animals', 'pet', 'pets', 'cat', 'cats',
                'dog', 'dogs', 'paw', 'paws', 'zoo', 'wildlife'}), 'paw'),
    (frozenset({'sport', 'sports', 'soccer', 'football', 'ball',
                'basketball'}), 'ball'),
    (frozenset({'dice', 'die', 'random', 'roll', 'luck', 'chance'}), 'dice'),
    (frozenset({'robot', 'robots', 'machine', 'coding', 'code',
                'program', 'programming', 'algorithm', 'computer'}), 'robot'),
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


def request_icon_svg(provider, spec, plan):
    """Ask the model to draw this activity's icon; never raises.

    Returns a sanitized SVG string, or None when the feature is off,
    the provider cannot draw, or the reply fails sanitization — the
    caller then falls back to render_activity_icon().
    """
    if os.environ.get('AOD_AI_ICON', 'on').lower() in (
            'off', '0', 'no', 'false'):
        return None
    generate_text = getattr(provider, 'generate_text', None)
    if not callable(generate_text):
        return None

    try:
        response = generate_text(
            build_icon_system_prompt(),
            build_icon_user_prompt(spec, plan),
        )
    except Exception as error:
        logging.warning('Icon drawing call failed: %s',
                        _redact_provider_value(error, provider))
        return None

    if _contains_provider_secret(response, provider):
        logging.warning('Model icon contained credential material')
        return None

    icon = sanitize_icon_svg(response)
    if icon is None:
        logging.warning('Model icon failed sanitization; using fallback')
    return icon


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
