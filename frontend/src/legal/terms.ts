/** The end-user agreement.
 *
 *  Kept as data rather than markup so one source feeds the signup gate, the
 *  standalone /terms page and any future PDF, and so the VERSION travels with
 *  the text. Acceptance is recorded against that version: when this changes,
 *  bump it, because "they agreed" has to mean "they agreed to this".
 *
 *  NOT LEGAL ADVICE. This was drafted to be clear and to cover the intended
 *  ground; it has not been reviewed by a lawyer, and several clauses below
 *  (liability caps, indemnity, and the data licence) are limited or overridden
 *  by law in some places — notably consumer sales, and personal data of people
 *  in the EU/UK. Have counsel review before relying on it.
 */

export const TERMS_VERSION = '2026-07-30'
export const TERMS_EFFECTIVE = '30 July 2026'

export interface TermsSection {
  heading: string
  paragraphs?: string[]
  bullets?: string[]
}

export const TERMS: TermsSection[] = [
  {
    heading: '1. What this agreement is',
    paragraphs: [
      'This is the agreement between you (“you”, and any organisation you sign up on behalf of) ' +
      'and the provider of Taktline (“we”, “us”). It covers your use of the Taktline software, ' +
      'website and hosted service (together, “the Service”).',
      'By ticking the box and creating an account you accept every part of it. If you are ' +
      'accepting on behalf of a company, you confirm you are authorised to bind that company. ' +
      'If you do not accept, do not use the Service.',
    ],
  },
  {
    heading: '2. What Taktline is — and what it is not',
    paragraphs: [
      'Taktline is a planning and visualisation tool. It draws your manufacturing flow, tracks ' +
      'lot cards through it, and reports timings you record.',
    ],
    bullets: [
      'It is NOT a safety system, an interlock, an alarm system, or any part of a control loop. ' +
      'Never use it to make or prevent a safety decision.',
      'It is NOT a system of record for regulatory, quality, financial, tax or traceability ' +
      'purposes. If you need records of that kind, keep them elsewhere.',
      'It is NOT a backup of your production data, and it is not designed for archival retention.',
      'It does not verify that what it shows matches your physical floor. Only you can do that.',
    ],
  },
  {
    heading: '3. Your line remains yours',
    paragraphs: [
      'You are solely responsible for your manufacturing operation and for every decision taken ' +
      'in it, whether or not that decision was informed by the Service.',
    ],
    bullets: [
      'You are responsible for the accuracy of everything you enter, import or connect — station ' +
      'layouts, routes, weights, products, orders and integrations.',
      'You are responsible for verifying any figure, suggestion, forecast or recommendation the ' +
      'Service produces before acting on it. Outputs may be wrong, stale, incomplete or absent.',
      'You are responsible for the safety, legality, quality and continuity of your production, ' +
      'for your staff and equipment, and for compliance with every law and standard that applies ' +
      'to you.',
      'You are responsible for your own account security, for who you invite, and for what they do.',
      'You are responsible for keeping your own independent backups of anything you cannot afford ' +
      'to lose.',
    ],
  },
  {
    heading: '4. Provided “as is” — no warranty',
    paragraphs: [
      'The Service is provided AS IS and AS AVAILABLE, with all faults and without warranty of ' +
      'any kind. To the fullest extent permitted by law we disclaim all warranties, express, ' +
      'implied and statutory, including merchantability, fitness for a particular purpose, ' +
      'accuracy, quiet enjoyment and non-infringement.',
      'We do not warrant that the Service will be uninterrupted, timely, secure, error-free, or ' +
      'that any data will be preserved, recoverable or accurate. We may change, suspend, limit ' +
      'or discontinue any part of it at any time.',
      'No advice or information you obtain from us creates any warranty not stated here.',
    ],
  },
  {
    heading: '5. Limitation of liability',
    paragraphs: [
      'To the fullest extent permitted by law, we are not liable for any indirect, incidental, ' +
      'special, consequential, exemplary or punitive damages, nor for any loss of production, ' +
      'output, revenue, profit, goodwill, contracts, business or anticipated savings, nor for ' +
      'any LOSS OR CORRUPTION OF DATA, nor for the cost of substitute goods or services — ' +
      'however caused and on any theory of liability, and even if we were told such damages ' +
      'were possible.',
      'Our total aggregate liability arising out of or relating to this agreement or the Service, ' +
      'for all claims combined, will not exceed the greater of (a) the fees you actually paid us ' +
      'for the Service in the three months immediately before the event giving rise to the claim, ' +
      'or (b) fifty euros (€50).',
      'These limits apply even if a remedy fails of its essential purpose. Nothing here excludes ' +
      'liability that cannot lawfully be excluded — including liability for death or personal ' +
      'injury caused by negligence, or for fraud.',
    ],
  },
  {
    heading: '6. You indemnify us',
    paragraphs: [
      'You will defend, indemnify and hold us harmless — together with our officers, employees ' +
      'and contractors — against any claim, demand, proceeding, loss, liability, damage, fine, ' +
      'penalty, cost and expense (including reasonable legal fees) arising out of or relating to:',
    ],
    bullets: [
      'your use of the Service, and any decision, action or omission in your operation;',
      'any damage, injury, defect, delay, downtime, scrap, recall, loss of production, or LOSS OR ' +
      'CORRUPTION OF DATA connected with your use of the Service;',
      'anything you enter, import, connect or transmit, and any claim that it infringes someone ' +
      'else’s rights or breaches any law;',
      'your breach of this agreement, and any act or omission of anyone you gave access to.',
    ],
  },
  {
    heading: '7. Your data, and what we do with it',
    paragraphs: [
      'Your data is stored and processed on servers we operate or rent, which may be located in ' +
      'countries other than yours. By using the Service you agree to that storage and transfer.',
      'You keep ownership of your data. You grant us a worldwide, royalty-free licence to host, ' +
      'store, copy, process, transmit, analyse and display it in order to:',
    ],
    bullets: [
      'operate, secure, support and troubleshoot the Service for you;',
      'improve and develop the Service and our models, including by analysing how lines are ' +
      'drawn and run;',
      'produce statistics, benchmarks and insights, and to give you data-driven advice on ' +
      'improving your line.',
    ],
  },
  {
    heading: '7a. Limits we place on ourselves',
    bullets: [
      'Anything we publish, share, or use beyond serving your own account will be AGGREGATED or ' +
      'DE-IDENTIFIED, so that it does not identify you, your company, your customers or your ' +
      'staff.',
      'We do not sell your data.',
      'Our staff access identifiable data only to support you, to keep the Service running, or ' +
      'where the law requires it — and support access is time-boxed and logged.',
      'Advice we generate is informational only. It is not engineering, safety, legal or ' +
      'financial advice, and section 3 still applies to every decision you take on it.',
      'You can export your data at any time, and ask us to delete your account. Aggregated and ' +
      'de-identified material that can no longer be linked to you may remain in use.',
    ],
  },
  {
    heading: '8. Availability, backups and deletion',
    paragraphs: [
      'We do not promise any level of availability and offer no service credits. We take ' +
      'reasonable care with backups but do not guarantee that any particular data can be ' +
      'recovered, and we are not liable if it cannot be. Keep your own copies.',
      'We may delete accounts and their data after prolonged inactivity, on termination, or ' +
      'where a plan says so — trial and sandbox accounts expressly so.',
    ],
  },
  {
    heading: '9. Acceptable use',
    bullets: [
      'Do not use the Service where its failure or inaccuracy could lead to injury, death, or ' +
      'severe environmental or property damage.',
      'Do not attempt to breach or probe its security, access another tenant’s data, or ' +
      'circumvent limits.',
      'Do not upload anything unlawful, malicious, or that you lack the right to upload.',
      'Do not resell or provide the Service to third parties without our written agreement.',
    ],
  },
  {
    heading: '10. Fees, term and termination',
    paragraphs: [
      'Paid plans are billed as described at purchase. Fees are non-refundable except where the ' +
      'law requires otherwise.',
      'You may stop using the Service and close your account at any time. We may suspend or ' +
      'terminate your access if you breach this agreement, if required by law, or on reasonable ' +
      'notice. Sections 3 to 7a, 11 and 12 survive termination.',
    ],
  },
  {
    heading: '11. Changes to this agreement',
    paragraphs: [
      'We may update this agreement. If we make a material change we will ask you to accept the ' +
      'new version the next time you sign in. Continuing to use the Service after a change takes ' +
      'effect means you accept it. Each acceptance is recorded against the version you were shown.',
    ],
  },
  {
    heading: '12. Law, disputes and the rest',
    paragraphs: [
      'This agreement is governed by the laws of the State of Colorado, USA, without regard to ' +
      'its conflict-of-laws rules, and the state and federal courts located in Boulder County, ' +
      'Colorado have exclusive jurisdiction — except where mandatory law in your country of ' +
      'residence gives you the right to bring proceedings elsewhere.',
      'If any provision is held unenforceable, it is limited to the minimum extent necessary and ' +
      'the rest stays in force. Our failure to enforce a provision is not a waiver of it. You may ' +
      'not assign this agreement without our consent; we may assign it in connection with a ' +
      'merger, acquisition or sale of assets.',
      'This is the entire agreement between us about the Service and replaces anything said ' +
      'before it.',
    ],
  },
]
