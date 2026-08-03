import type { Lang } from './languages'

/**
 * The dictionary. One file, all languages per key, so a missing translation
 * is visible in the diff that should have added it — five parallel files hide
 * exactly that. `i18n.test.ts` asserts every key carries every language.
 *
 * The starter set is the **operator surface**: the person the languages exist
 * for is the one holding the tablet, so START comes before Settings. Adding a
 * key here and calling `t('the.key')` is the whole workflow; `{n}`-style
 * placeholders are substituted by `t`.
 *
 * These translations are machine-drafted. Before the first non-English shop
 * goes live, have a native speaker read their column — a wrong word on a
 * START button is not a cosmetic bug.
 */
export const STRINGS: Record<string, Record<Lang, string>> = {
  // ── Operator: the big verbs ──────────────────────────────────────────────
  'op.start': {
    en: 'START', es: 'INICIAR', 'fr-CA': 'DÉMARRER',
    my: 'စတင်ရန်', ht: 'KÒMANSE',
  },
  'op.starting': {
    en: 'STARTING…', es: 'INICIANDO…', 'fr-CA': 'DÉMARRAGE…',
    my: 'စတင်နေသည်…', ht: 'AP KÒMANSE…',
  },
  'op.stop': {
    en: 'STOP', es: 'DETENER', 'fr-CA': 'ARRÊTER',
    my: 'ရပ်ရန်', ht: 'KANPE',
  },
  'op.move': {
    en: 'MOVE', es: 'MOVER', 'fr-CA': 'DÉPLACER',
    my: 'ရွှေ့ရန်', ht: 'DEPLASE',
  },
  'op.moving': {
    en: 'MOVING…', es: 'MOVIENDO…', 'fr-CA': 'DÉPLACEMENT…',
    my: 'ရွှေ့နေသည်…', ht: 'AP DEPLASE…',
  },
  'op.moveTo': {
    en: 'MOVE → {dest}', es: 'MOVER → {dest}', 'fr-CA': 'DÉPLACER → {dest}',
    my: 'ရွှေ့ရန် → {dest}', ht: 'DEPLASE → {dest}',
  },
  'op.moveUnits.one': {
    en: 'MOVE {n} UNIT', es: 'MOVER {n} UNIDAD', 'fr-CA': 'DÉPLACER {n} UNITÉ',
    my: '{n} ယူနစ် ရွှေ့ရန်', ht: 'DEPLASE {n} INITE',
  },
  'op.moveUnits.many': {
    en: 'MOVE {n} UNITS', es: 'MOVER {n} UNIDADES', 'fr-CA': 'DÉPLACER {n} UNITÉS',
    my: '{n} ယူနစ် ရွှေ့ရန်', ht: 'DEPLASE {n} INITE',
  },
  'op.done': {
    en: 'DONE', es: 'LISTO', 'fr-CA': 'TERMINÉ',
    my: 'ပြီးပါပြီ', ht: 'FINI',
  },
  'op.finishing': {
    en: 'FINISHING…', es: 'FINALIZANDO…', 'fr-CA': 'FINALISATION…',
    my: 'ပြီးဆုံးနေသည်…', ht: 'AP FINI…',
  },
  'op.continueWorking': {
    en: 'CONTINUE WORKING', es: 'SEGUIR TRABAJANDO', 'fr-CA': 'CONTINUER LE TRAVAIL',
    my: 'ဆက်လက်လုပ်ဆောင်ရန်', ht: 'KONTINYE TRAVAY',
  },
  'op.units': {
    en: 'units', es: 'unidades', 'fr-CA': 'unités',
    my: 'ယူနစ်', ht: 'inite',
  },
  'op.selectLot': {
    en: 'Select a lot to work on, then press START',
    es: 'Seleccione un lote para trabajar y presione INICIAR',
    'fr-CA': 'Sélectionnez un lot à travailler, puis appuyez sur DÉMARRER',
    my: 'လုပ်ဆောင်ရန် လော့တစ်ခုကို ရွေးပြီး စတင်ရန် ကိုနှိပ်ပါ',
    ht: 'Chwazi yon lo pou travay, epi peze KÒMANSE',
  },
  'op.selectPrecursors': {
    en: 'Select precursor lots and press MERGE to build the assembly, then work on it',
    es: 'Seleccione los lotes precursores y presione MERGE para armar el conjunto; luego trabájelo',
    'fr-CA': 'Sélectionnez les lots précurseurs et appuyez sur MERGE pour monter l’assemblage, puis travaillez-le',
    my: 'အစိတ်အပိုင်း လော့များကို ရွေးပြီး MERGE နှိပ်၍ တပ်ဆင်မှုကို တည်ဆောက်ပါ၊ ထို့နောက် ဆက်လုပ်ပါ',
    ht: 'Chwazi lo pyès yo epi peze MERGE pou monte ansanm lan, apre sa travay sou li',
  },
  'op.wholelot': {
    en: 'This lot moves whole — deal the units across the routes.',
    es: 'Este lote se mueve entero: reparta las unidades entre las rutas.',
    'fr-CA': 'Ce lot se déplace en entier — répartissez les unités entre les routes.',
    my: 'ဤလော့သည် တစ်ခုလုံးရွှေ့သည် — ယူနစ်များကို လမ်းကြောင်းများအလိုက် ခွဲဝေပါ။',
    ht: 'Lo sa a deplase an antye — separe inite yo sou wout yo.',
  },
  'op.unitsAt.one': {
    en: '{n} unit at', es: '{n} unidad en', 'fr-CA': '{n} unité à',
    my: '{n} ယူနစ် — ', ht: '{n} inite nan',
  },
  'op.unitsAt.many': {
    en: '{n} units at', es: '{n} unidades en', 'fr-CA': '{n} unités à',
    my: '{n} ယူနစ် — ', ht: '{n} inite nan',
  },

  // ── The language picker itself ───────────────────────────────────────────
  'lang.label': {
    en: 'Language', es: 'Idioma', 'fr-CA': 'Langue',
    my: 'ဘာသာစကား', ht: 'Lang',
  },
  'lang.companyLabel': {
    en: 'Languages this company runs in',
    es: 'Idiomas en los que trabaja esta empresa',
    'fr-CA': 'Langues de travail de cette entreprise',
    my: 'ဤကုမ္ပဏီ အသုံးပြုသော ဘာသာစကားများ',
    ht: 'Lang konpayi sa a travay ladan yo',
  },
  'lang.companyHint': {
    en: 'Invited operators choose their language from this set.',
    es: 'Los operadores invitados eligen su idioma de esta lista.',
    'fr-CA': 'Les opérateurs invités choisissent leur langue dans cette liste.',
    my: 'ဖိတ်ခေါ်ထားသော အော်ပရေတာများသည် ဤစာရင်းမှ ဘာသာစကားကို ရွေးချယ်နိုင်သည်။',
    ht: 'Operatè envite yo chwazi lang yo nan lis sa a.',
  },
}
