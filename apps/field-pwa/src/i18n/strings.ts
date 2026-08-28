/**
 * Bilingual strings, Hindi first.
 *
 * Section 9.1 is specific about the ordering: "Hindi-first bilingual UI (Hindi
 * primary, English secondary -- not the reverse)". That is a real constraint,
 * not a preference, and it shows up here in two ways.
 *
 * First, Hindi is written as the source and English as the secondary rendering,
 * rather than Hindi being a translation of English strings. Phrasing that reads
 * naturally to an Anganwadi worker wins over phrasing that maps neatly onto an
 * English key name.
 *
 * Second, both languages ship in the bundle and the toggle is local. The app is
 * offline-first; a language switch that needed the network would be useless in
 * exactly the situation it is most likely to be used.
 *
 * `k` is a deliberately terse helper so the string table stays scannable side
 * by side -- a reviewer should be able to read the Hindi and English columns
 * together and spot a mismatch.
 */

export type Lang = "hi" | "en";

const k = (hi: string, en: string) => ({ hi, en });

export const strings = {
  appName: k("पोषण नेत्र", "PoshanNetra"),
  appTagline: k("भोजन निगरानी", "Meal monitoring"),

  // --- Navigation -------------------------------------------------------
  navHome: k("मुख्य", "Home"),
  navCapture: k("फ़ोटो", "Capture"),
  navGrowth: k("वज़न", "Growth"),
  navQueue: k("सिंक", "Sync"),
  navSettings: k("सेटिंग", "Settings"),

  // --- Sign in ----------------------------------------------------------
  signInTitle: k("साइन इन करें", "Sign in"),
  phoneLabel: k("मोबाइल नंबर", "Mobile number"),
  phoneHint: k("वही नंबर जो आंगनवाड़ी में दर्ज है", "The number registered at your centre"),
  signInAction: k("कोड भेजें", "Send code"),
  signInFailed: k("यह नंबर दर्ज नहीं है", "This number is not registered"),

  // --- One-time code ----------------------------------------------------
  otpLabel: k("6 अंकों का कोड", "6-digit code"),
  otpSentTo: k("कोड भेजा गया", "Code sent to"),
  otpHint: k("SMS में आया कोड भरें", "Enter the code from the SMS"),
  otpVerify: k("साइन इन करें", "Sign in"),
  otpWrong: k("यह कोड सही नहीं है", "That code is not correct"),
  otpResend: k("कोड दोबारा भेजें", "Send the code again"),
  otpResendWait: k("दोबारा भेजने के लिए रुकें", "Wait before sending again"),
  otpExpiresIn: k("कोड की समय-सीमा", "Code expires in"),
  otpTooMany: k(
    "बहुत बार कोशिश हुई। थोड़ी देर बाद फिर कोशिश करें।",
    "Too many attempts. Try again in a little while.",
  ),
  changeNumber: k("नंबर बदलें", "Change number"),
  otpDemoCode: k("डेमो कोड", "Demo code"),
  sessionExpired: k(
    "सत्र समाप्त हो गया — कृपया दोबारा साइन इन करें। आपका सुरक्षित काम नहीं जाएगा।",
    "Your session ended — please sign in again. Your saved work is not lost.",
  ),
  signInOffline: k(
    "साइन इन के लिए इंटरनेट ज़रूरी है। एक बार साइन इन करने के बाद ऐप बिना इंटरनेट चलेगा।",
    "Sign in needs internet. After signing in once, the app works without it.",
  ),
  signOut: k("साइन आउट", "Sign out"),
  signOutWarning: k(
    "साइन आउट करने पर बिना भेजा हुआ काम रह जाएगा। पहले सिंक करें।",
    "Signing out leaves unsent work behind. Sync first.",
  ),

  // --- Home -------------------------------------------------------------
  greeting: k("नमस्ते", "Hello"),
  todayTitle: k("आज का काम", "Today"),
  statCaptured: k("आज की थालियाँ", "Plates today"),
  statPending: k("भेजना बाकी", "Waiting to send"),
  statMeasured: k("इस माह मापे गए", "Measured this month"),
  statChildren: k("कुल बच्चे", "Children"),
  notMeasuredTitle: k("इस माह वज़न बाकी", "Not yet measured this month"),
  notMeasuredEmpty: k("सभी बच्चों का वज़न हो चुका है", "Every child has been measured"),
  andMore: k("और", "and"),
  more: k("और बच्चे", "more children"),

  // --- Capture ----------------------------------------------------------
  captureTitle: k("थाली की फ़ोटो", "Plate photo"),
  selectChild: k("बच्चा चुनें", "Select child"),
  selectChildPlaceholder: k("— चुनें —", "— Select —"),
  searchChild: k("नाम खोजें", "Search by name"),
  mealType: k("भोजन", "Meal"),
  mealBreakfast: k("नाश्ता", "Breakfast"),
  mealLunch: k("दोपहर का भोजन", "Lunch"),
  mealThr: k("घर ले जाने का राशन", "Take-home ration"),
  takePhoto: k("फ़ोटो खींचें", "Take photo"),
  retakePhoto: k("दोबारा खींचें", "Retake"),
  usePhoto: k("यह फ़ोटो ठीक है", "Use this photo"),
  saveCapture: k("सुरक्षित करें", "Save"),
  captureSaved: k("सुरक्षित हो गया", "Saved"),
  captureSavedDetail: k(
    "फ़ोटो फ़ोन में सुरक्षित है। इंटरनेट आने पर अपने आप भेज दी जाएगी।",
    "Saved on this phone. It will send by itself when internet returns.",
  ),
  captureAnother: k("अगली थाली", "Next plate"),
  noChildSelected: k("पहले बच्चा चुनें", "Select a child first"),
  noPhotoTaken: k("पहले फ़ोटो खींचें", "Take a photo first"),
  cameraUnavailable: k(
    "कैमरा नहीं खुल पाया — फ़ोन का कैमरा ऐप इस्तेमाल करें",
    "Camera did not open — using your phone's camera app",
  ),
  cameraPermission: k(
    "कैमरे की अनुमति दें, या फ़ोन का कैमरा ऐप इस्तेमाल करें",
    "Allow camera access, or use your phone's camera app",
  ),
  photoTooLarge: k("फ़ोटो बहुत बड़ी है", "Photo is too large"),
  plateOnly: k(
    "सिर्फ़ थाली की फ़ोटो लें। बच्चे की फ़ोटो कभी न लें।",
    "Photograph the plate only. Never photograph the child.",
  ),

  // --- Growth -----------------------------------------------------------
  growthTitle: k("वज़न और लंबाई", "Weight and height"),
  heightLabel: k("लंबाई (सेंटीमीटर)", "Height (cm)"),
  weightLabel: k("वज़न (किलोग्राम)", "Weight (kg)"),
  heightHint: k("जैसे 88.5", "For example 88.5"),
  weightHint: k("जैसे 11.2", "For example 11.2"),
  saveGrowth: k("दर्ज करें", "Record"),
  growthSaved: k("दर्ज हो गया", "Recorded"),
  classification: k("स्थिति", "Status"),
  classNormal: k("सामान्य", "Normal"),
  classMam: k("मध्यम कुपोषण", "Moderate malnutrition"),
  classSam: k("गंभीर कुपोषण", "Severe malnutrition"),
  classStunted: k("बौनापन", "Stunted"),
  classUnderweight: k("कम वज़न", "Underweight"),
  samAdvice: k(
    "इस बच्चे को तुरंत पर्यवेक्षक को दिखाएँ।",
    "Refer this child to your supervisor immediately.",
  ),
  growthNeedsInternet: k(
    "वज़न दर्ज करने के लिए इंटरनेट ज़रूरी है, क्योंकि स्थिति सर्वर पर तय होती है।",
    "Recording growth needs internet, because the status is computed on the server.",
  ),
  implausibleReading: k(
    "यह माप सही नहीं लग रहा। कृपया दोबारा मापें।",
    "This measurement does not look right. Please measure again.",
  ),
  invalidNumber: k("सही संख्या भरें", "Enter a valid number"),

  // --- Sync queue -------------------------------------------------------
  queueTitle: k("भेजने की सूची", "Send queue"),
  syncNow: k("अभी भेजें", "Send now"),
  syncing: k("भेजा जा रहा है…", "Sending…"),
  syncDone: k("सब भेज दिया गया", "Everything sent"),
  queueEmpty: k("भेजने के लिए कुछ नहीं है", "Nothing waiting to send"),
  statusPending: k("भेजना बाकी", "Waiting"),
  statusSyncing: k("भेजा जा रहा है", "Sending"),
  statusSynced: k("भेज दिया", "Sent"),
  statusFailed: k("नहीं भेजा जा सका", "Could not send"),
  retryItem: k("दोबारा कोशिश करें", "Try again"),
  deleteItem: k("हटाएँ", "Delete"),
  deleteConfirm: k(
    "यह फ़ोटो हमेशा के लिए हट जाएगी। पक्का?",
    "This photo will be deleted permanently. Are you sure?",
  ),
  attemptsLabel: k("कोशिशें", "Attempts"),
  offlineBanner: k("इंटरनेट नहीं है", "No internet"),
  offlineDetail: k(
    "काम करते रहें — सब कुछ फ़ोन में सुरक्षित रहेगा और बाद में अपने आप भेज दिया जाएगा।",
    "Keep working — everything is saved on this phone and will send later by itself.",
  ),
  onlineAgain: k("इंटरनेट वापस आ गया", "Internet is back"),

  // --- Settings ---------------------------------------------------------
  settingsTitle: k("सेटिंग", "Settings"),
  language: k("भाषा", "Language"),
  languageHindi: k("हिन्दी", "Hindi"),
  languageEnglish: k("अंग्रेज़ी", "English"),
  theme: k("रंग-रूप", "Appearance"),
  themeLight: k("दिन", "Light"),
  themeDark: k("रात", "Dark"),
  themeSystem: k("फ़ोन जैसा", "System"),
  themeSunlight: k("तेज़ धूप", "Bright sunlight"),
  themeSunlightHint: k(
    "बाहर धूप में पढ़ने के लिए — ज़्यादा गहरा और बड़ा अक्षर",
    "For reading outdoors — maximum contrast, larger text",
  ),
  storageTitle: k("फ़ोन की जगह", "Phone storage"),
  storageUsed: k("इस्तेमाल", "Used"),
  storageLow: k(
    "फ़ोन में जगह कम है। कृपया सिंक करें ताकि पुरानी फ़ोटो हटाई जा सकें।",
    "Storage is running low. Please sync so old photos can be removed.",
  ),
  refreshChildren: k("बच्चों की सूची ताज़ा करें", "Refresh children list")  ,
  lastUpdated: k("आख़िरी बार", "Last updated"),
  never: k("कभी नहीं", "Never"),
  centre: k("केंद्र", "Centre"),

  // --- Shared -----------------------------------------------------------
  cancel: k("रद्द करें", "Cancel"),
  confirm: k("हाँ", "Yes"),
  back: k("वापस", "Back"),
  loading: k("रुकिए…", "Loading…"),
  errorGeneric: k("कुछ गड़बड़ हो गई", "Something went wrong"),
  tryAgain: k("दोबारा कोशिश करें", "Try again"),
  skipToContent: k("मुख्य सामग्री पर जाएँ", "Skip to main content"),
  years: k("साल", "years"),
  months: k("माह", "months"),
  updateAvailable: k("नया अपडेट तैयार है", "An update is ready"),
  updateAction: k("अपडेट करें", "Update"),
} as const;

export type StringKey = keyof typeof strings;

export function translate(key: StringKey, lang: Lang): string {
  return strings[key][lang];
}

/** Both languages for one key, for places that show them together. */
export function both(key: StringKey): { hi: string; en: string } {
  return strings[key];
}
