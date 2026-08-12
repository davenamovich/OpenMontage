"""Constants for the romance pipeline.

Kept in one place so stage directors, the engine, the web UI, and tests all
agree on the vocabulary.
"""

from __future__ import annotations

# Canonical genres — see pipeline_defs/youtube-romance-story.yaml metadata.genres
GENRES = [
    "second_chance", "forbidden_love", "friends_to_lovers", "enemies_to_lovers",
    "secret_identity", "workplace", "small_town", "billionaire",
    "unexpected_inheritance", "marriage_of_convenience", "long_distance",
    "lost_love", "love_after_divorce", "mature", "holiday",
    "romantic_mystery", "romantic_suspense", "betrayal_redemption",
    "family_disapproval", "class_difference", "accidental_meeting",
    "fake_relationship", "single_parent", "military_reunion",
    "historical", "supernatural",
]

GENRE_LABELS = {
    "second_chance": "Second-Chance Romance",
    "forbidden_love": "Forbidden Love",
    "friends_to_lovers": "Friends to Lovers",
    "enemies_to_lovers": "Enemies to Lovers",
    "secret_identity": "Secret Identity",
    "workplace": "Workplace Romance",
    "small_town": "Small-Town Romance",
    "billionaire": "Billionaire Romance",
    "unexpected_inheritance": "Unexpected Inheritance",
    "marriage_of_convenience": "Marriage of Convenience",
    "long_distance": "Long-Distance Romance",
    "lost_love": "Lost Love",
    "love_after_divorce": "Love After Divorce",
    "mature": "Mature Romance",
    "holiday": "Holiday Romance",
    "romantic_mystery": "Romantic Mystery",
    "romantic_suspense": "Romantic Suspense",
    "betrayal_redemption": "Betrayal and Redemption",
    "family_disapproval": "Family Disapproval",
    "class_difference": "Class Difference",
    "accidental_meeting": "Accidental Meeting",
    "fake_relationship": "Fake Relationship",
    "single_parent": "Single-Parent Romance",
    "military_reunion": "Military Reunion",
    "historical": "Historical Romance",
    "supernatural": "Supernatural Romance",
}

FORMATS = ["long_form", "short", "serialized", "confession", "text_message"]

FORMAT_LABELS = {
    "long_form": "Long-Form Episode (8-15 min, 16:9)",
    "short": "Romance Short (45-90 sec, 9:16)",
    "serialized": "Serialized Romance (continuing series)",
    "confession": "Confession Story (first-person, intimate)",
    "text_message": "Text-Message Romance (chat-style)",
}

VISUAL_MODES = ["economical", "hybrid", "cinematic"]

VISUAL_MODE_LABELS = {
    "economical": "Economical (stills + animation, lowest cost)",
    "hybrid": "Hybrid (character stills + stock env + AI-video hero moments)",
    "cinematic": "Cinematic (AI-generated video clips, higher budget)",
}

# Eras / decades — affects clothing, architecture, technology, social norms
ERAS = [
    "ancient_world",    # antiquity (Greece, Rome, Egypt)
    "medieval",         # 5th-15th century
    "renaissance",      # 15th-17th century
    "regency",          # early 1800s (Jane Austen era)
    "victorian",        # 1837-1901
    "edwardian",        # 1901-1914
    "roaring_20s",      # 1920s
    "great_depression", # 1930s
    "ww2_era",          # 1940s
    "postwar",          # 1950s
    "swinging_60s",     # 1960s
    "disco_70s",        # 1970s
    "neon_80s",         # 1980s
    "grunge_90s",       # 1990s
    "y2k",              # 2000s
    "modern",           # 2010s-present
    "near_future",      # 2030-2050
    "far_future",       # 2050+
    "post_apocalyptic", # after collapse
    "steampunk",        # alt-Victorian sci-fi
    "cyberpunk",        # alt-near-future neon
    "fantasy",          # unspecified magical realm
]

ERA_LABELS = {
    "ancient_world": "Ancient World (Antiquity)",
    "medieval": "Medieval (5th-15th century)",
    "renaissance": "Renaissance (15th-17th century)",
    "regency": "Regency Era (early 1800s)",
    "victorian": "Victorian Era (1837-1901)",
    "edwardian": "Edwardian Era (1901-1914)",
    "roaring_20s": "Roaring 1920s",
    "great_depression": "Great Depression (1930s)",
    "ww2_era": "WWII Era (1940s)",
    "postwar": "Postwar / 1950s",
    "swinging_60s": "Swinging 1960s",
    "disco_70s": "Disco Era (1970s)",
    "neon_80s": "Neon 1980s",
    "grunge_90s": "Grunge 1990s",
    "y2k": "Y2K Era (2000s)",
    "modern": "Modern (2010s-present)",
    "near_future": "Near Future (2030-2050)",
    "far_future": "Far Future (2050+)",
    "post_apocalyptic": "Post-Apocalyptic",
    "steampunk": "Steampunk (alt-Victorian)",
    "cyberpunk": "Cyberpunk (alt-near-future)",
    "fantasy": "Fantasy (magical realm)",
}

# Era-specific visual cues that get appended to image prompts
# These ensure clothing, architecture, and props match the era
ERA_VISUAL_CUES = {
    "ancient_world": "ancient marble architecture, togas, tunics, olive groves, bronze jewelry, sandals, amphorae, classical columns",
    "medieval": "stone castles, tapestries, torchlight, long gowns, surcoats, chainmail, codices, wooden halls, thatched roofs",
    "renaissance": "frescoed walls, velvet gowns with slashed sleeves, ruffled collars, oil-lamp light, ornate palazzos, lutes",
    "regency": "empire-waist muslin dresses, tailcoats with cravats, bonnets, Georgian architecture, assembly rooms, carriage rides",
    "victorian": "corseted bustle dresses, top hats, gaslight, lace, parasols, horse-drawn carriages, brick townhouses, soot",
    "edwardian": "S-curve silhouettes, lace blouses, straw boater hats, early automobiles, garden parties, telegraph wires",
    "roaring_20s": "flapper dresses with fringe, bobbed hair, cloche hats, suspenders, art deco interiors, speakeasies, jazz age",
    "great_depression": "dusty overalls, feed-sack dresses, rundown farmhouses, soup kitchens, fedoras, worn leather shoes",
    "ww2_era": "utility dresses, victory rolls hair, fedoras, military uniforms, rationing posters, air-raid shelters",
    "postwar": "full skirts with petticoats, cardigan sets, greaser leather jackets, diners with chrome stools, pastel kitchens",
    "swinging_60s": "miniskirts, go-go boots, mod shift dresses, skinny ties, geometric wallpapers, Volkswagen Beetles",
    "disco_70s": "bell-bottoms, platform shoes, polyester jumpsuits, afros, mood lighting, velvet furniture, cassette tapes",
    "neon_80s": "shoulder pads, big hair, neon windbreakers, leg warmers, mall arcades, cassette boomboxes, synthwave palette",
    "grunge_90s": "flannel shirts, ripped jeans, combat boots, chokers, tamagotchis, dial-up computers, coffee shop booths",
    "y2k": "low-rise jeans, baby tees, frosted tips, flip phones, chunky highlights, Y2K metallics, early iPods",
    "modern": "smartphones, skinny jeans, athleisure, minimalist interiors, laptops, earbuds, ride-share cars, stainless steel",
    "near_future": "augmented reality glasses, sleek wearables, holographic displays, electric vehicles, smart home panels",
    "far_future": "spaceships, zero-gravity habitats, metallic bodysuits, neural interfaces, starfields, domed cities",
    "post_apocalyptic": "salvaged layered clothing, gas masks, rusted vehicles, overgrown ruins, patched canvas, makeshift weapons",
    "steampunk": "brass goggles, corsets with gears, top hats with clockwork, steam pipes, airships, copper tones, Victorian-industrial",
    "cyberpunk": "neon-lit rain-slick streets, holographic ads, chrome prosthetics, LED jackets, megacorp towers, katana, drones",
    "fantasy": "medieval-fantasy gowns, enchanted forests, castles on cliffs, glowing runes, parchment scrolls, taverns, dragons",
}

# Visual styles — affects the artistic look of generated images
VISUAL_STYLES = [
    "cinematic_realism",    # photorealistic, film-like (default)
    "photographic",         # clean photography, studio lighting
    "oil_painting",         # classical oil painting
    "watercolor",           # soft watercolor wash
    "anime",                # Japanese anime style
    "ghibli",               # Studio Ghibli inspired
    "caricature",           # exaggerated cartoon caricature
    "comic_book",           # American comic book inked style
    "manga",                # black and white manga
    "pixar_3d",             # 3D animated (Pixar-like)
    "claymation",           # stop-motion clay
    "noir_black_white",     # film noir, high contrast B&W
    "vintage_film",         # aged sepia / 8mm film grain
    "digital_art",          # polished digital painting
    "concept_art",          # concept art sketch
    "minimalist",           # flat minimalist illustration
    "storybook",            # children's book illustration
    "gothic",               # dark gothic atmosphere
    "impressionist",        # Impressionist painting (Monet-like)
    "art_deco",             # Art Deco poster style
]

VISUAL_STYLE_LABELS = {
    "cinematic_realism": "Cinematic Realism (photorealistic, film-like)",
    "photographic": "Photographic (clean studio photography)",
    "oil_painting": "Oil Painting (classical fine art)",
    "watercolor": "Watercolor (soft washes)",
    "anime": "Anime (Japanese animation)",
    "ghibli": "Studio Ghibli (soft anime)",
    "caricature": "Caricature (exaggerated cartoon)",
    "comic_book": "Comic Book (American inked)",
    "manga": "Manga (B&W Japanese comic)",
    "pixar_3d": "Pixar 3D (animated film)",
    "claymation": "Claymation (stop-motion)",
    "noir_black_white": "Film Noir (B&W high contrast)",
    "vintage_film": "Vintage Film (sepia, grain)",
    "digital_art": "Digital Art (polished)",
    "concept_art": "Concept Art (sketch)",
    "minimalist": "Minimalist (flat illustration)",
    "storybook": "Storybook (children's book)",
    "gothic": "Gothic (dark atmosphere)",
    "impressionist": "Impressionist (Monet-like)",
    "art_deco": "Art Deco (poster style)",
}

# Style modifier strings appended to image prompts
VISUAL_STYLE_MODIFIERS = {
    "cinematic_realism": "cinematic realism, photorealistic, film grain, shallow depth of field, natural lighting, 85mm lens, anamorphic",
    "photographic": "professional photography, studio lighting, sharp focus, high resolution, color-graded",
    "oil_painting": "oil painting, visible brushstrokes, rich textures, classical fine art, museum quality, chiaroscuro",
    "watercolor": "watercolor painting, soft washes, bleeding colors, paper texture, delicate, impressionistic",
    "anime": "anime style, cel shading, vibrant colors, clean lineart, dramatic expressions, Japanese animation",
    "ghibli": "Studio Ghibli inspired, soft hand-painted backgrounds, gentle lighting, warm palette, whimsical",
    "caricature": "caricature, exaggerated features, oversized heads, cartoonish proportions, humorous, expressive",
    "comic_book": "comic book style, bold ink outlines, halftone shading, dynamic poses, speech bubbles, Pop Art",
    "manga": "manga style, black and white, screentone, dramatic linework, speed lines, expressive eyes",
    "pixar_3d": "Pixar-style 3D animation, subsurface scattering, soft global illumination, stylized proportions, polished",
    "claymation": "claymation, stop-motion animation, visible fingerprints, clay texture, handcrafted, charming",
    "noir_black_white": "film noir, high contrast black and white, dramatic shadows, venetian blind lighting, moody",
    "vintage_film": "vintage film, sepia tones, 8mm grain, light leaks, scratched emulsion, nostalgic, aged",
    "digital_art": "digital painting, polished, concept art quality, ArtStation trending, detailed, vibrant",
    "concept_art": "concept art, loose brushwork, sketch quality, environment design, matte painting, atmospheric",
    "minimalist": "minimalist illustration, flat colors, simple shapes, limited palette, clean, modern",
    "storybook": "children's storybook illustration, soft pastels, whimsical, hand-drawn, cozy, storybook palette",
    "gothic": "gothic atmosphere, dark moody lighting, ornate details, fog, candlelight, melancholic, romantic gothic",
    "impressionist": "Impressionist painting, visible brushstrokes, plein air, soft light, Monet-like, dappled color",
    "art_deco": "Art Deco poster style, geometric patterns, gold and black, elegant, 1920s graphic design, symmetrical",
}

# Negative prompt modifiers per style (what to avoid)
VISUAL_STYLE_NEGATIVES = {
    "cinematic_realism": "cartoon, anime, illustration, painting, low quality, blurry, deformed",
    "photographic": "cartoon, painting, illustration, anime, low quality, blurry",
    "oil_painting": "photograph, 3D render, cartoon, anime, digital art, photorealistic",
    "watercolor": "photograph, 3D render, oil painting, photorealistic, sharp lines",
    "anime": "photorealistic, 3D render, oil painting, photograph, western cartoon",
    "ghibli": "photorealistic, 3D render, dark, horror, photorealistic, sharp lines",
    "caricature": "photorealistic, realistic proportions, photograph, 3D render, serious",
    "comic_book": "photorealistic, 3D render, oil painting, watercolor, photorealistic",
    "manga": "color, photograph, 3D render, oil painting, photorealistic, anime color",
    "pixar_3d": "photorealistic, oil painting, watercolor, 2D illustration, photograph",
    "claymation": "photorealistic, 2D illustration, oil painting, smooth, CGI render",
    "noir_black_white": "color, vibrant, photograph, oil painting, anime, cartoon",
    "vintage_film": "clean digital, sharp, modern, photorealistic, HDR, oversaturated",
    "digital_art": "photograph, oil painting, watercolor, 3D render, photorealistic",
    "concept_art": "photograph, photorealistic, 3D render, polished, finished",
    "minimalist": "detailed, photorealistic, complex, busy, oil painting, 3D render",
    "storybook": "photorealistic, dark, horror, 3D render, photograph, sharp lines",
    "gothic": "bright, cheerful, pastel, minimalist, photograph, photorealistic",
    "impressionist": "photograph, 3D render, sharp focus, photorealistic, digital art",
    "art_deco": "photorealistic, oil painting, watercolor, 3D render, photograph",
}

# Required emotional beats for every long-form episode (in order)
EMOTIONAL_BEATS = [
    "opening_hook",
    "setup",
    "inciting_encounter",
    "rising_attraction",
    "complication",
    "midpoint_shift",
    "emotional_break",
    "final_choice",
    "payoff",
    "final_button",
]

BEAT_LABELS = {
    "opening_hook": "Opening Hook",
    "setup": "Setup",
    "inciting_encounter": "Inciting Encounter",
    "rising_attraction": "Rising Attraction",
    "complication": "Complication",
    "midpoint_shift": "Midpoint Shift",
    "emotional_break": "Emotional Break",
    "final_choice": "Final Choice",
    "payoff": "Payoff",
    "final_button": "Final Button",
}

# Retention beats — sprinkled throughout long-form videos
RETENTION_BEATS = [
    "new_question",
    "revelation",
    "decision",
    "reversal",
    "emotional_confession",
    "visual_change",
    "escalation",
]

# Default narrator voices per language (z-ai voices)
DEFAULT_VOICES = {
    "en": "tongtong",
    "zh": "tongtong",
}

# WPM calibration — used to convert target_duration → target_word_count
WORDS_PER_MINUTE = {
    "long_form": 150,
    "short": 165,        # slightly faster for Shorts
    "serialized": 150,
    "confession": 130,   # slower, more intimate
    "text_message": 145,
}

# Duration ranges per format (seconds)
DURATION_RANGE = {
    "long_form": (480, 900),       # 8-15 min
    "short": (45, 90),
    "serialized": (480, 900),
    "confession": (180, 600),
    "text_message": (60, 180),
}

# Quality score thresholds — if any falls below, revision is required
QUALITY_THRESHOLDS = {
    "hook_strength": 7,
    "originality": 6,
    "ending_satisfaction": 7,
    "continuity": 7,
}
# Other dimensions just need to be ≥ 5
QUALITY_MINIMUM = 5
