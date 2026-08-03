/** The privacy policy.
 *
 *  Same shape as `terms.ts` and for the same reasons: data rather than markup,
 *  one source for the /privacy page and anything that quotes it, a VERSION
 *  that travels with the text. Unlike the terms, nothing is *accepted* against
 *  this version — it exists so a reader (or App Store reviewer) can see when
 *  the text last changed.
 *
 *  Everything stated here is grounded in what the code actually does — the
 *  session cookie is httpOnly, passwords are argon2id, crash reports expire at
 *  30 days, Plausible is cookieless, supplier links are fetched by the
 *  browser. If the code changes, change this text and bump the version.
 *
 *  NOT LEGAL ADVICE. Drafted to be clear and honest; not reviewed by a
 *  lawyer. GDPR/UK and some US state laws grant rights beyond what is written
 *  here — the intent is to honour them anyway, but have counsel review before
 *  relying on it.
 */

export const PRIVACY_VERSION = '2026-08-02.1'
export const PRIVACY_EFFECTIVE = '2 August 2026'

export interface PrivacySection {
  heading: string
  paragraphs?: string[]
  bullets?: string[]
}

export const PRIVACY: PrivacySection[] = [
  {
    heading: '1. Who we are, and what this covers',
    paragraphs: [
      'Taktline is operated by Taktline LLC (“we”, “us”). This policy covers taktline.com, the ' +
      'hosted Taktline service, and the Taktline mobile app — which is the same service in a ' +
      'native shell. It explains what we collect, why, where it lives, and how to get it back ' +
      'or have it removed.',
      'The short version: we collect what the product needs to work, we do not sell it, we do ' +
      'not run ads, and there is no tracking of you across other sites or apps.',
    ],
  },
  {
    heading: '2. What we collect, and why',
    bullets: [
      'Your account: name, email address, and a password we store only as a hash (argon2id) — ' +
      'we cannot read it. Plus which companies you belong to and your role in each.',
      'Your production data: the stations, routes, products, lot cards, orders, work-session ' +
      'timings and floor-plan images you and your team enter. This is the product doing its ' +
      'job, and it belongs to you (see our terms, section 7).',
      'Data your integrations send: if you connect an ERP or shop system, the order details it ' +
      'sends (customer name, references, ship-to and similar) are stored on the orders and lot ' +
      'cards they relate to. API keys are stored only as hashes.',
      'Operational records: server logs (IP address, request metadata), per-company usage ' +
      'counts, and an audit trail of actions taken in your account — who moved which lot, when. ' +
      'These exist to run, secure and support the service.',
      'Crash reports: if the app crashes in your browser, the error and basic browser ' +
      'information are sent to our own server so we can fix it. These are deleted after 30 days.',
      'Analytics on the public pages: we use Plausible, which is cookieless and aggregate — it ' +
      'tells us how many people visited, not who you are. There are no advertising or ' +
      'cross-site trackers anywhere on the site or in the app.',
    ],
  },
  {
    heading: '3. Cookies and local storage',
    bullets: [
      'A session cookie (httpOnly — scripts cannot read it) keeps you signed in, and a CSRF ' +
      'cookie protects your session against forged requests. Both are strictly necessary; ' +
      'neither tracks you, and there are no third-party cookies.',
      'Your browser’s local storage holds convenience state: which company is active, your ' +
      'theme, and a read-only snapshot of your own board so it still renders during a network ' +
      'outage. It is cleared when you sign out.',
    ],
  },
  {
    heading: '4. Email we send',
    paragraphs: [
      'Transactional only: verifying your address, invitations you or your team trigger, ' +
      'password resets, and notices about your account or subscription. We do not add you to ' +
      'marketing lists or share your address for anyone else’s.',
    ],
  },
  {
    heading: '5. Where your data lives, and who processes it',
    paragraphs: [
      'Taktline runs on infrastructure we rent from a small number of providers ' +
      '(“subprocessors”), each doing one job:',
    ],
    bullets: [
      'Render (render.com) hosts our servers and database, in the United States.',
      'Resend delivers the transactional email above, and therefore processes recipient ' +
      'addresses.',
      'Plausible provides the cookieless analytics on the public pages.',
      'Stripe processes payments if you buy a paid plan. Card and bank details go directly to ' +
      'Stripe; we never see or store them — we hold only your plan, invoices and billing ' +
      'status.',
      'If you are outside the United States, using the service means your data is transferred ' +
      'to and stored there.',
    ],
  },
  {
    heading: '6. What we share — and what we never do',
    bullets: [
      'We do not sell your data, to anyone, for anything.',
      'We show no ads and share nothing with ad networks or data brokers.',
      'Data goes only to the subprocessors above, or where the law compels us — and if it does, ' +
      'we will tell you unless we are legally barred from doing so.',
      'Anything we publish or analyse beyond serving your own account is aggregated or ' +
      'de-identified so it cannot identify you, your company, your customers or your staff.',
      'Our staff access identifiable data only to support you or keep the service running; ' +
      'support access is time-boxed and logged.',
    ],
  },
  {
    heading: '7. Pages you choose to make public',
    bullets: [
      'Order-tracking links show that order’s progress to anyone holding the link. The links ' +
      'are unguessable and marked so search engines do not index them — but a link you send is ' +
      'yours to send, so share it as deliberately as you would the information on it. The ' +
      'feature is off until a company turns it on.',
      'A supplier tracking link you paste into your board is fetched by your own browser, not ' +
      'by our servers — we never hold your supplier’s credentials or fetch on your behalf.',
    ],
  },
  {
    heading: '8. How long we keep things',
    bullets: [
      'Your account and production data: for as long as the account exists. Sandbox (try-it) ' +
      'accounts delete themselves after 7 days.',
      'Crash reports: 30 days. Server logs and backups roll off on a schedule measured in days ' +
      'to weeks, not years.',
      'You can export your data at any time — the statistics workbook and the line file are ' +
      'both built for exactly that — and closing your account removes the data it held, after ' +
      'which only aggregated or de-identified material that cannot be linked to you may remain.',
    ],
  },
  {
    heading: '9. Your rights',
    paragraphs: [
      'Wherever you live, we honour the same set of rights: see what we hold about you, correct ' +
      'it, export it, and have it deleted. Email us (section 12) and we will act on it — ' +
      'identity checked, no forms, no fee. If your local law (GDPR, UK GDPR, CCPA and similar) ' +
      'grants you more, you have that too, including the right to complain to your supervisory ' +
      'authority.',
    ],
  },
  {
    heading: '10. Security',
    paragraphs: [
      'Everything travels over TLS. Passwords are hashed with argon2id, sessions and API keys ' +
      'are stored as hashes, tenants are isolated from one another, and destructive operations ' +
      'are audited. No system is impenetrable — if we learn of a breach affecting your data, we ' +
      'will notify you without undue delay.',
    ],
  },
  {
    heading: '11. Children',
    paragraphs: [
      'Taktline is a workplace tool, not directed at children, and we do not knowingly collect ' +
      'data from anyone under 16. If you believe a child has created an account, tell us and we ' +
      'will delete it.',
    ],
  },
  {
    heading: '12. Changes, and how to reach us',
    paragraphs: [
      'When this policy changes, the new version appears here with a new date and version ' +
      'number; a material change will be flagged when you next sign in.',
      'Questions, requests, or anything this page should say and does not: ' +
      'privacy@taktline.com, or the contact form on taktline.com. Taktline LLC, Indiana, USA.',
    ],
  },
]
