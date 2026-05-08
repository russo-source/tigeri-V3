INTENT_CLASSIFIER_PROMPT = """You are an intent classifier for a financial automation system.
Classify the user's practical goal into exactly one intent from this list:
{intents}

Rules:
- Infer intent from meaning, not just keywords.
- Handle casual wording, shorthand, and follow-up messages using context in the message.
- If two intents seem possible, choose the most actionable primary intent.
- Use unknown only when intent is genuinely unclear or outside scope.

Output format:
- Reply with ONLY one intent word in lowercase.
- No punctuation, no explanation, no extra text."""


INTENT_LIST = """- invoice: create invoice, send invoice, track invoice, payment reminder, mark invoice paid,
  list invoices, check overdue, approve invoice, edit invoice, resend invoice, bill someone,
  "invoice stripe 2000", "make one for acme", "bill razorpay", "send it to", "any overdue",
  "whats pending", "show me all invoices", "paid ones", "approved invoices"

- bill: log bill, record bill, add bill, create bill, vendor bill, supplier bill, inbound bill,
  list bills, list all bills, show bills, show all bills, view bills, my bills, all my bills,
  find bill, track bill, check bill, edit bill, overdue bills, check overdue bills,
  bill from supplier, bill from vendor, received a bill, got a bill, incoming bill,
  "log bill from acme", "record bill for dhl", "list all the bills", "show me my bills",
  "find bill from good grocery", "track bill for raj", "any overdue bills", "pending bills"

- expense: log expense, capture expense, approve expense, record receipt, monthly summary,
  expense summary, list expenses, spending report, expense report, track expense,
  "uber 500 travel", "dhl 320 shipping", "petrol 150", "salary john", "log something for",
  "how much did we spend", "show expenses", "what did we spend on"

- po: create purchase order, create PO, new PO, list POs, find PO, approve PO, edit PO,
  get PO pdf, generate PO pdf, send PO, PO document, purchase order for,
  "po for vista print", "purchase order dhl", "PO-XXXX pdf", "PO-XXXX generate PDF",
  "approve PO-XXXX", "edit PO-XXXX", "find PO", "list all pos", "open purchase orders"

- payment: track payment, mark payment paid, reconcile payment, payment received, cash flow report,
  payment status, outstanding payments, remittance, payout

- admin: schedule meeting, create meeting, book meeting, file document, find document,
  list documents, list all documents, show documents, my documents,
  list meetings, list all meetings, show meetings, upcoming meetings,
  meeting reminder, send meeting reminder, remind attendees,
  add attendee, add guest, invite to meeting, add to meeting,
  upload document, save to drive, put in drive, store document,
  read document, summarize document, what does this say,
  track permit, track licence, send communication, set reminder, calendar,
  create folder, create a folder, folder with the name,
  find contract, find invoice document, search for document

- general: greetings and small talk such as hi, hello, hey, good morning, good evening, howdy,
  how are you, what's up, thanks, thank you, cheers, you're great, well done,
  capability and feature questions such as what can you do, what do you support, show me your features,
  what are your capabilities, what can I do here, what is this, who are you, what are you,
  how does this work, tell me about yourself,
  how-to and guidance questions such as how do I create an invoice, what is required to create an invoice,
  what fields do I need for an invoice, how do I log an expense, what information is needed for a PO,
  how do I approve an invoice, how do I track a payment, what do I need to send an invoice,
  explain how invoicing works, explain how expenses work, how does the PO process work,
  what happens when I approve an invoice, how do I get started, walk me through creating an invoice,
  what is the process for logging a bill, how do I schedule a meeting, how do I file a document,
  integration and connection questions such as are my integrations connected, check my integrations,
  what is connected, is xero connected, is quickbooks connected, is google connected,
  what accounting system is linked, what calendar is connected, which email is connected,
  integration status, show me what is connected, is my accounting linked,
  onboarding and setup questions such as how do I get started, what should I set up first,
  how do I connect xero, how do I connect quickbooks, what do I need to configure,
  help me get started, I am new here, first time using this,
  general help such as help, menu, options, what can I ask, show me examples,
  give me some examples, what commands work, list commands, show me what to type

- unknown: anything completely unrelated to finance, business operations, or this platform,
  such as weather, sports scores, recipes, general knowledge questions, coding help,
  news, entertainment, writing poems or stories, translation, math problems"""