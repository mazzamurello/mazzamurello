// The sprite: Sibillo, an original mazzamurello, drawn as SVG and animated with CSS (UX-012 to UX-014, ADR-0070).
// It is decorative: hidden from assistive technologies, which get the same information as text.

export type Pose = "greeting" | "thinking" | "searching" | "reading" | "writing" | "running" | "answering" | "listening" | "waiting" | "error";

const LN = "var(--c-line)";
const SK = "var(--c-skin)";
const RED = "var(--c-hat)";
const WOOD = "var(--c-wood)";

const limb = (d: string, color: string, w = 3.6) =>
  `<path d="${d}" fill="none" stroke="${LN}" stroke-width="${w + 2.4}" stroke-linecap="round" stroke-linejoin="round"/>` +
  `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;
const hand = (x: number, y: number, r = 3.3) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${SK}" stroke="${LN}" stroke-width="1.3"/>`;
const ARM_L = limb("M91,128 Q84,141 82,152", SK) + hand(82, 153);
const ARM_R = limb("M109,128 Q116,141 118,152", SK) + hand(118, 153);

// Static markup: no user content ever reaches it.
const FIGURE = `
  <ellipse cx="100" cy="214" rx="34" ry="4.5" fill="var(--fg)" opacity=".1"/>
  <g class="fig">
    ${limb("M95,158 Q91,182 89,203", RED, 4.4)}${limb("M105,158 Q109,182 111,203", RED, 4.4)}
    <path d="M93,200 Q88,212 73,207 Q64,203 66,196 Q73,204 87,200 Z" fill="var(--c-hat-shade)" stroke="${LN}" stroke-width="1.4" stroke-linejoin="round"/>
    <path d="M107,200 Q112,212 127,207 Q136,203 134,196 Q127,204 113,200 Z" fill="var(--c-hat-shade)" stroke="${LN}" stroke-width="1.4" stroke-linejoin="round"/>
    <path d="M91,124 Q100,119 109,124 L116,158 Q100,165 84,158 Z" fill="var(--c-tunic)" stroke="${LN}" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="M87,146 Q100,151 113,146" stroke="var(--c-hat-shade)" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <g class="head">
      <path d="M83,100 L55,86 L84,113 Z" fill="${SK}" stroke="${LN}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M80,102 L64,92" stroke="var(--c-blush)" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M117,100 L145,86 L116,113 Z" fill="${SK}" stroke="${LN}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M120,102 L136,92" stroke="var(--c-blush)" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="100" cy="103" r="21" fill="${SK}" stroke="${LN}" stroke-width="1.6"/>
      <circle cx="87" cy="111" r="4" fill="var(--c-blush)" opacity=".6"/>
      <circle cx="113" cy="111" r="4" fill="var(--c-blush)" opacity=".6"/>
      <path d="M88,104 Q92,99 96,104 M104,104 Q108,99 112,104" stroke="${LN}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path d="M100,106 Q102.5,109 100,110" stroke="${LN}" stroke-width="1.3" fill="none" stroke-linecap="round"/>
      <path d="M91,113 Q100,123 109,113 Q100,116.5 91,113 Z" fill="var(--c-mouth)" stroke="${LN}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M81,93 L73,108 L80,104 L78,114 L86,102 L85,95 Z" fill="var(--c-hair)" stroke="${LN}" stroke-width="1.2" stroke-linejoin="round"/>
      <path d="M119,93 L127,108 L120,104 L122,114 L114,102 L115,95 Z" fill="var(--c-hair)" stroke="${LN}" stroke-width="1.2" stroke-linejoin="round"/>
      <g class="hat">
        <path d="M77,96 C73,72 85,50 101,36 C113,25 128,17 147,17 C139,24 134,33 131,45 C128,61 127,79 124,96 Z" fill="${RED}" stroke="${LN}" stroke-width="1.6" stroke-linejoin="round"/>
        <path d="M107,42 C117,52 121,72 119,95" stroke="var(--c-hat-shade)" stroke-width="2.5" fill="none" stroke-linecap="round" opacity=".85"/>
        <path d="M75,97 Q100,105 126,97 L125,90 Q100,97 76,90 Z" fill="var(--c-hat-shade)" stroke="${LN}" stroke-width="1.4" stroke-linejoin="round"/>
      </g>
    </g>
    <g class="pose pose-idle">${ARM_L}${ARM_R}</g>
    <g class="pose pose-wave">${ARM_L}<g class="wave-arm">${limb("M109,128 Q122,121 127,104", SK)}${hand(127, 102, 3.9)}</g></g>
    <g class="pose pose-listen">${ARM_L}
      <g class="listen-arm">${limb("M109,128 Q127,126 129,109", SK)}${hand(129, 106, 3.9)}</g>
      <g class="waves" stroke="${LN}" stroke-width="1.8" fill="none" stroke-linecap="round">
        <path class="wave" d="M150,96 Q155,104 150,112"/><path class="wave w2" d="M157,91 Q164,104 157,117"/><path class="wave w3" d="M164,86 Q173,104 164,122"/>
      </g>
    </g>
    <g class="pose pose-think">
      ${limb("M91,128 Q86,141 97,146", SK)}${hand(97, 146)}
      ${limb("M109,128 C119,139 113,128 105,123", SK)}${hand(105, 123)}
      <g fill="var(--c-paper)" stroke="${LN}" stroke-width="1.2">
        <circle class="dot" cx="134" cy="80" r="2.4"/><circle class="dot d2" cx="142" cy="67" r="3.3"/><circle class="dot d3" cx="152" cy="52" r="4.4"/>
      </g>
    </g>
    <g class="pose pose-search">${ARM_L}
      <g class="lens-arm">${limb("M109,128 Q122,135 131,124", SK)}${limb("M132,121 L137,113", WOOD, 3.2)}
        <circle cx="143.5" cy="104" r="10" fill="var(--c-glass)" stroke="${LN}" stroke-width="2.6"/>
        <path d="M137.5,101 Q139.5,96.5 144,95.8" stroke="var(--c-paper)" stroke-width="1.8" fill="none" stroke-linecap="round"/>
        ${hand(131, 123)}
      </g>
    </g>
    <g class="pose pose-read">
      <path d="M75,141 L100,146 L125,141 L125,160 L100,165 L75,160 Z" fill="${WOOD}" stroke="${LN}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M78,139 Q90,137 100,143 L100,160 Q90,155 78,157 Z" fill="var(--c-paper)" stroke="${LN}" stroke-width="1.1" stroke-linejoin="round"/>
      <path d="M122,139 Q110,137 100,143 L100,160 Q110,155 122,157 Z" fill="var(--c-paper)" stroke="${LN}" stroke-width="1.1" stroke-linejoin="round"/>
      <path d="M82,146 Q90,145 96,148 M82,151 Q90,150 96,153 M104,148 Q110,145 118,146 M104,153 Q110,150 118,151" stroke="${LN}" stroke-width=".9" opacity=".45" fill="none"/>
      <path class="page-flip" d="M122,139 Q110,137 100,143 L100,160 Q110,155 122,157 Z" fill="var(--c-paper)" stroke="${LN}" stroke-width="1.1" stroke-linejoin="round"/>
      ${limb("M91,128 Q82,141 86,150", SK)}${hand(86, 150)}${limb("M109,128 Q118,141 114,150", SK)}${hand(114, 150)}
    </g>
    <g class="pose pose-write">
      <g transform="rotate(-10 80 148)">
        <rect x="67" y="133" width="26" height="30" rx="2.5" fill="var(--c-paper)" stroke="${LN}" stroke-width="1.4"/>
        <path class="ink" d="M71,142 h17 M71,148 h17 M71,154 h12" stroke="${LN}" stroke-width="1.1" fill="none" stroke-linecap="round"/>
        <path d="M70,133 v-2.5 M75,133 v-2.5 M80,133 v-2.5 M85,133 v-2.5 M90,133 v-2.5" stroke="${LN}" stroke-width="1.4" stroke-linecap="round"/>
      </g>
      ${limb("M91,128 Q83,140 85,151", SK)}${hand(85, 151)}
      <g class="pencil-arm">${limb("M109,128 Q115,146 93,147", SK)}${limb("M89,151 L98,139", "var(--c-hair)", 2.6)}
        <path d="M89,151 l-1.6,2.4" stroke="${LN}" stroke-width="1.6" stroke-linecap="round"/>${hand(93, 147)}
      </g>
    </g>
    <g class="pose pose-knock">${ARM_L}
      <g class="mallet-arm">${limb("M109,128 Q122,124 128,110", SK)}${limb("M128,112 L128,88", WOOD, 3)}
        <rect x="118" y="78" width="20" height="11" rx="3" fill="${WOOD}" stroke="${LN}" stroke-width="1.4"/>${hand(128, 109)}
      </g>
      <path class="bang" d="M158,98 l7,-4 M160,106 h8 M158,114 l7,4" stroke="${LN}" stroke-width="1.8" stroke-linecap="round" fill="none"/>
    </g>
    <g class="pose pose-sign">${ARM_L}
      <g class="sign-arm">${limb("M109,128 Q126,124 134,110", SK)}${limb("M136,110 L158,86", WOOD, 3)}
        <rect x="138" y="56" width="48" height="31" rx="4" fill="var(--c-paper)" stroke="${LN}" stroke-width="1.8"/>
        <path d="M162,62 v11" stroke="${RED}" stroke-width="4.2" stroke-linecap="round"/><circle cx="162" cy="80" r="2.4" fill="${RED}"/>
        ${hand(134, 109)}
      </g>
    </g>
  </g>`;

/** The sprite in a pose; `head` shows only the head and hat, for small places such as the brand. */
export function Sprite({ pose, className = "", head = false }: { pose: Pose; className?: string; head?: boolean }) {
  return (
    <svg
      className={`sprite ${className}`}
      data-sprite-pose={pose}
      viewBox={head ? "52 12 96 118" : "0 0 200 230"}
      aria-hidden="true"
      focusable="false"
      dangerouslySetInnerHTML={{ __html: FIGURE }}
    />
  );
}
