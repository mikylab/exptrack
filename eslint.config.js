// ESLint flat config for the exptrack dashboard JS (dev-only).
//
// The dashboard ships as ~22 JS sections concatenated into a single inline
// <script>, so every top-level function/var is an intentional shared global
// across files. That makes `no-undef` pure noise here (a name defined in
// core.js is "undefined" when detail.js is linted alone), so it's left off —
// cross-file handler wiring is instead guarded by the Python-side
// tests/test_dashboard_js_integrity.py, which verifies every inline on*=
// handler references a defined function. What ESLint adds is single-file
// correctness: duplicate keys/args/cases, unreachable code, accidental
// assignments, const reassignment, typeof typos, etc.
export default [
  {
    files: ["exptrack/dashboard/static/js/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        fetch: "readonly",
        localStorage: "readonly",
        sessionStorage: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        requestAnimationFrame: "readonly",
        alert: "readonly",
        confirm: "readonly",
        prompt: "readonly",
        location: "readonly",
        navigator: "readonly",
        URL: "readonly",
        Blob: "readonly",
        FileReader: "readonly",
        Image: "readonly",
        Chart: "readonly",
        Intl: "readonly",
        atob: "readonly",
        btoa: "readonly",
        getComputedStyle: "readonly",
      },
    },
    rules: {
      "no-dupe-keys": "error",
      "no-dupe-args": "error",
      "no-dupe-class-members": "error",
      "no-duplicate-case": "error",
      "no-unreachable": "error",
      // "except-parens" permits the deliberate `while ((m = re.exec(s)) !==
      // null)` idiom (extra parens signal intent) while still catching an
      // accidental `if (x = y)`.
      "no-cond-assign": ["error", "except-parens"],
      "no-constant-condition": ["error", { checkLoops: false }],
      "no-self-assign": "error",
      "no-self-compare": "error",
      "no-const-assign": "error",
      "no-func-assign": "error",
      "no-class-assign": "error",
      "no-compare-neg-zero": "error",
      "use-isnan": "error",
      "valid-typeof": "error",
      "no-fallthrough": "error",
      "no-irregular-whitespace": "error",
      "no-unsafe-negation": "error",
      "no-unused-vars": "off",
    },
  },
];
