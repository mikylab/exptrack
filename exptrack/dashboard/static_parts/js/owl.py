"""Owl mascot animation, speech bubble, and click counter easter egg."""

JS_OWL = r"""
// ── Owl mascot ──────────────────────────────────────────────────────────────
const owlPhrases = [
  'Hoo hoo! Track all the things!',
  'Another experiment? Wise choice.',
  'Remember to tag your best runs!',
  'I never forget a metric.',
  'Did you try a lower learning rate?',
  'Diff your code, diff your life.',
  'Compare runs to find the signal.',
  'Notes help future-you understand past-you.',
  'Zero dependencies, infinite wisdom.',
  'Local-first, always.',
  'Reproducibility is a superpower!',
  'Git diff captured. You\'re welcome.',
  'Have you tried turning it off and on again?',
  'Every experiment teaches something!',
  'Science is organized curiosity.',
  'Log it or lose it!',
  'Hyperparameters are just suggestions.',
];
const owlContextPhrases = {
  delete: ['Are you sure? I\'ll miss that one...', 'Cleaning house? Smart owl.', 'Gone but not forgotten... actually, gone.'],
  compare: ['Let\'s see who wins!', 'Side by side, insight arrives.', 'May the best model win!'],
  export: ['Sharing is caring!', 'Data to go!', 'Knowledge wants to be free!'],
  tag: ['Good labeling, wise human!', 'Tags make finding things a hoot!', 'Organized minds run better experiments.'],
  empty: ['No experiments yet? Go run something!', 'An empty lab is full of potential.', 'The best experiment is the next one!'],
  welcome: ['Welcome back! What shall we track today?', 'Hoo! Good to see you!', 'Ready to science? Let\'s go!'],
  rename: ['A good name tells a story.', 'Identity matters!'],
  note: ['Write it down before you forget!', 'Future you will thank present you.'],
  artifact: ['Artifacts secured!', 'Saving your treasures.'],
  filter: ['Narrowing it down? Smart move.', 'Finding the needle in the haystack!'],
  click: ['Hoo?', '*tilts head*', '*blinks curiously*', 'Yes?', '*ruffles feathers*', '*does a little dance*'],
};
let owlSpeechTimer = null;

function owlSay(msg, anim) {
  const el = document.getElementById('owl-speech');
  if (!el) return;
  el.textContent = msg;
  // Position fixed below the owl
  const container = document.getElementById('header-owl');
  if (container) {
    const rect = container.getBoundingClientRect();
    el.style.top = (rect.bottom + 6) + 'px';
    el.style.left = (rect.left + rect.width / 2) + 'px';
    el.style.transform = 'translateX(-50%)';
  }
  el.style.display = 'block';
  if (owlSpeechTimer) clearTimeout(owlSpeechTimer);
  owlSpeechTimer = setTimeout(() => { el.style.display = 'none'; }, 3500);
  // Trigger animation
  const mascot = document.querySelector('.owl-mascot');
  if (mascot && anim) {
    mascot.classList.remove('owl-bounce', 'owl-wiggle');
    void mascot.offsetWidth; // force reflow
    mascot.classList.add(anim);
    setTimeout(() => mascot.classList.remove(anim), 600);
  }
}

function owlSpeak(context) {
  const phrases = context && owlContextPhrases[context] ? owlContextPhrases[context] : owlPhrases;
  const anim = context === 'delete' ? 'owl-wiggle' : 'owl-bounce';
  owlSay(phrases[Math.floor(Math.random() * phrases.length)], anim);
}
"""

# Sidebar, view switching, selection
