import os

from app import (
    build_details,
    generate_original_fallback_names,
    generate_original_names_with_openai,
    has_awkward_original_shape,
    syllable_count,
)


CURATED_PROFILES = [
    {
        'pet_type': 'Girl',
        'discovery_style': 'Hidden gems',
        'style': 'Modern',
        'vibe': 'Elegant and understated',
        'cultural_context': 'International / blended',
        'timeless_vs_distinctive': 'Mostly distinctive',
        'familiarity_preference': 'Recognizable but not overused',
        'pronunciation_importance': 'Helpful but not absolute',
        'partner_alignment': 'One likes classic, one likes fresh',
        'notes': 'Sibling name is Theo',
    },
]


ORIGINAL_PROFILES = [
    {
        'label': 'International modern girl',
        'pet_type': 'Girl',
        'style': 'Modern',
        'vibe': 'Elegant and understated',
        'discovery_style': 'Familiar but fresh',
        'familiarity_preference': 'Recognizable but not overused',
        'pronunciation_importance': 'Helpful but not absolute',
        'starting_letter': '',
        'length_preference': 'Balanced 2 syllables',
        'cultural_context': 'International / blended',
        'avoid_feel': 'Too trendy',
        'notes': 'Sibling name is Theo',
    },
    {
        'label': 'French classic boy',
        'pet_type': 'Boy',
        'style': 'Classic',
        'vibe': 'Warm and grounded',
        'discovery_style': 'Safe favorites',
        'familiarity_preference': 'Very familiar and easy',
        'pronunciation_importance': 'Helpful but not absolute',
        'starting_letter': '',
        'length_preference': 'Short and crisp',
        'cultural_context': 'French',
        'avoid_feel': '',
        'notes': '',
    },
    {
        'label': 'Japanese modern neutral',
        'pet_type': 'Gender-neutral',
        'style': 'Modern',
        'vibe': 'Bright and lively',
        'discovery_style': 'Bold discoveries',
        'familiarity_preference': 'Memorable and rarer',
        'pronunciation_importance': 'Open to slight friction',
        'starting_letter': '',
        'length_preference': 'Open to either',
        'cultural_context': 'Japanese',
        'avoid_feel': '',
        'notes': '',
    },
    {
        'label': 'Irish romantic girl',
        'pet_type': 'Girl',
        'style': 'Soft and romantic',
        'vibe': 'Romantic and lyrical',
        'discovery_style': 'Hidden gems',
        'familiarity_preference': 'A little less common',
        'pronunciation_importance': 'Helpful but not absolute',
        'starting_letter': 'L',
        'length_preference': 'Flowing 3 syllables',
        'cultural_context': 'Irish',
        'avoid_feel': '',
        'notes': '',
    },
]


def describe_original_name(item):
    name = item['name']
    warnings = []
    if has_awkward_original_shape(name):
        warnings.append('awkward-shape')
    syllables = syllable_count(name)
    if syllables > 4:
        warnings.append(f'{syllables}-syllable')
    warning_text = f" [{', '.join(warnings)}]" if warnings else ''
    return f"- {name} ({item['pronunciation']}){warning_text}"


def main():
    has_openai_key = bool(os.getenv('OPENAI_API_KEY'))
    print(f"OPENAI_API_KEY: {'present' if has_openai_key else 'missing'}")
    print()

    print('CURATED PROMPT DETAILS')
    print('=' * 22)
    for profile in CURATED_PROFILES:
        print(build_details(profile))
        print()

    print('ORIGINAL OUTPUTS')
    print('=' * 16)
    for profile in ORIGINAL_PROFILES:
        print(profile['label'])
        names = generate_original_names_with_openai(profile)
        source = 'openai'
        if not names:
            names = generate_original_fallback_names(profile)
            source = 'fallback'
        print(f"source: {source}")
        for item in names:
            print(describe_original_name(item))
        print()


if __name__ == '__main__':
    main()
