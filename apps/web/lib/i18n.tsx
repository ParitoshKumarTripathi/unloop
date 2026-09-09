'use client';

import { type ReactNode, createContext, useContext, useEffect, useMemo } from 'react';

export type UiLanguage = 'english' | 'hindi';

const HI: Record<string, string> = {
  'brand.kicker': 'अनलूप समाधान एजेंट',
  'chrome.builtWith': 'इसके साथ बनाया गया',
  'theme.toggle': 'रंग योजना बदलें',
  'theme.dark': 'गहरी रंग योजना चालू करें',
  'theme.light': 'हल्की रंग योजना चालू करें',
  'theme.system': 'सिस्टम की रंग योजना अपनाएँ',
  'welcome.title': 'ग्राहक सहायता जो गलती होने पर अपनी रणनीति बदलती है।',
  'welcome.description':
    'सहायता सेवा चुनें, कॉल शुरू करें और अपनी समस्या स्वाभाविक रूप से बताएँ। एजेंट जाँच कर सकता है, कार्रवाई कर सकता है, सुधार मिलने पर तरीका बदल सकता है और पूरी जानकारी के साथ मामला आगे भेज सकता है।',
  'welcome.domain': 'सहायता क्षेत्र चुनें',
  'welcome.domainLabel': 'सहायता क्षेत्र',
  'welcome.language': 'बातचीत की भाषा चुनें',
  'welcome.start': 'कॉल शुरू करें',
  'language.english': 'अंग्रेज़ी',
  'language.englishDescription': 'अंग्रेज़ी में बातचीत',
  'language.hindi': 'हिन्दी',
  'language.hindiDescription': 'हिन्दी में बातचीत',
  'scenario.banking': 'बैंकिंग',
  'scenario.bankingShort': 'ओटीपी नहीं मिला',
  'scenario.bankingDescription': 'खाता और भुगतान सहायता',
  'scenario.ecommerce': 'ई-कॉमर्स',
  'scenario.ecommerceShort': 'रिफंड नहीं मिला',
  'scenario.ecommerceDescription': 'ऑर्डर, रिटर्न और रिफंड सहायता',
  'scenario.restaurant': 'रेस्टोरेंट',
  'scenario.restaurantShort': 'रिजर्वेशन नहीं मिला',
  'scenario.restaurantDescription': 'मौजूदा रिजर्वेशन सहायता',
  'scenario.salon': 'सैलून',
  'scenario.salonShort': 'अपॉइंटमेंट बदला',
  'scenario.salonDescription': 'मौजूदा अपॉइंटमेंट सहायता',
  'scenario.hotel': 'होटल',
  'scenario.hotelShort': 'बुकिंग में अंतर',
  'scenario.hotelDescription': 'मौजूदा बुकिंग सहायता',
  'session.listening': 'एजेंट सुन रहा है, अपना सवाल पूछें',
  'session.thinking': 'सोच रहा है…',
  'session.type': 'अपना संदेश लिखें…',
  'session.send': 'भेजें',
  'session.sending': 'भेजा जा रहा है…',
  'session.endCall': 'कॉल समाप्त करें',
  'session.end': 'समाप्त',
  'session.controls': 'वॉइस सहायक नियंत्रण',
  'session.microphone': 'माइक्रोफ़ोन चालू या बंद करें',
  'session.transcript': 'बातचीत दिखाएँ या छिपाएँ',
  'session.startAudio': 'ऑडियो शुरू करें',
  'session.ended': 'सत्र समाप्त हुआ',
  'session.guide': 'त्वरित आरंभ मार्गदर्शिका देखें',
  'debug.waiting': 'एजेंट की समाधान स्थिति की प्रतीक्षा हो रही है।',
  'debug.start': 'शुरू करने के लिए कॉल चालू करें।',
  'debug.issue': 'समस्या',
  'debug.turn': 'बारी',
  'debug.session': 'सत्र',
  'debug.demoControls': 'डेमो नियंत्रण',
  'debug.demoHelp': 'केवल परीक्षण डेटा की स्थितियाँ बदलता है। बातचीत तय नहीं कर सकता।',
  'debug.delay': 'विलंब',
  'debug.none': 'कोई नहीं',
  'debug.clear': 'सब हटाएँ',
  'debug.scenario': 'डेमो प्रीसेट',
  'debug.scenarioHelp':
    'यह टेस्ट प्रोफ़ाइल केवल तय समय या विफलता की स्थिति जोड़ती है। SQLite ग्राहक रिकॉर्ड और बातचीत का लक्ष्य अलग रहते हैं।',
  'card.version': 'स्थिति संस्करण',
  'card.invalidated': 'अमान्य हुआ:',
  'card.noCorrections': 'अभी कोई सुधार नहीं। कुछ भी अमान्य नहीं हुआ है।',
  'card.hypotheses': 'संभावित कारण',
  'card.rejected': 'खारिज',
  'card.rejectedAt': 'पर खारिज',
  'card.facts': 'पुष्ट तथ्य',
  'card.noFacts': 'अभी कोई तथ्य पुष्ट नहीं हुआ।',
  'card.corrections': 'ग्राहक के सुधार',
  'card.noCallerCorrections': 'ग्राहक ने अभी किसी बात का खंडन नहीं किया।',
  'card.timeline': 'टूल समयरेखा',
  'card.done': 'पूरे',
  'card.inFlight': 'जारी',
  'card.fenced': 'रोके गए',
  'card.issued': 'जारी हुआ',
  'card.injected': 'जोड़ा गया',
  'card.fencedDetail': 'परिणाम साक्ष्य के रूप में रखा गया, बोलने से रोका गया',
  'card.spoke': 'बोला',
  'common.yes': 'हाँ',
  'common.no': 'नहीं',
  'card.noChecks': 'अभी कोई जाँच नहीं हुई।',
  'card.loop': 'लूप पहचान',
  'card.score': 'स्कोर',
  'card.strategy': 'रणनीति:',
  'card.escalation': 'मामला आगे भेजना:',
  'card.loopDetected': 'लूप मिला — रणनीति बदलनी होगी या मामला आगे भेजना होगा।',
  'card.heard': 'ग्राहक ने क्या सुना',
  'card.notSpoken': 'एजेंट ने अभी कुछ नहीं कहा।',
  'card.wordAligned': 'शब्द-संरेखित',
  'card.cutBeforeAudio':
    'ग्राहक तक आवाज़ पहुँचने से पहले रोक दिया गया — इसे बोला हुआ नहीं माना गया',
  'card.handoff': 'हैंडऑफ पैकेट',
  'card.notCreated': 'नहीं बनाया गया',
  'card.nothingToHandoff': 'अभी आगे भेजने के लिए कुछ नहीं है।',
  'card.confirmed': 'पुष्ट',
  'card.ruledOut': 'खारिज कारण',
  'card.conflicts': 'विरोधाभास',
  'card.open': 'खुले सवाल',
  'card.routedTo': 'भेजा गया:',
  'card.staleResult': 'पुराना परिणाम',
  'card.staleResults': 'पुराने परिणाम',
  'card.fencedThisCall': 'इस कॉल में रोके गए',
  'speech.waiting': 'एजेंट की प्रतीक्षा…',
  'speech.title': 'आवाज़',
  'speech.notJudged': 'निर्धारित मार्ग नहीं',
  'speech.model': 'मॉडल',
  'speech.voice': 'आवाज़',
  'speech.language': 'भाषा',
  'speech.transport': 'माध्यम',
  'speech.rate': 'दर',
  'speech.segment': 'खंड',
  'speech.region': 'क्षेत्र',
  'speech.endpoint': 'निर्धारित एंडपॉइंट',
};

const ENGINE_HI: Record<string, string> = {
  Banking: 'बैंकिंग',
  'E-commerce': 'ई-कॉमर्स',
  'Restaurant reservation support': 'रेस्टोरेंट रिजर्वेशन सहायता',
  'Salon appointment support': 'सैलून अपॉइंटमेंट सहायता',
  'Hotel booking support': 'होटल बुकिंग सहायता',
  'Debit card payment one-time password is not being received':
    'डेबिट कार्ड भुगतान का वन-टाइम पासवर्ड नहीं मिल रहा है',
  'Refund is marked processed but has not reached the customer':
    'रिफंड प्रोसेस दिख रहा है लेकिन ग्राहक तक नहीं पहुँचा',
  'Customer has confirmation but the restaurant cannot find the reservation':
    'ग्राहक के पास पुष्टि है लेकिन रेस्टोरेंट को रिजर्वेशन नहीं मिल रहा',
  'Confirmed salon appointment is missing, cancelled, or changed incorrectly':
    'कन्फर्म सैलून अपॉइंटमेंट गायब, रद्द या गलत तरीके से बदला गया है',
  'Customer has a confirmed hotel booking but the hotel cannot locate it':
    'ग्राहक के पास कन्फर्म होटल बुकिंग है लेकिन होटल उसे नहीं खोज पा रहा',
  'The debit card is blocked or deactivated': 'डेबिट कार्ड ब्लॉक या निष्क्रिय है',
  'Online or e-commerce transactions are switched off for the card':
    'कार्ड के ऑनलाइन या ई-कॉमर्स भुगतान बंद हैं',
  'The mobile number on file is unverified or out of date': 'दर्ज मोबाइल नंबर अपुष्ट या पुराना है',
  'The bank never generated an OTP for the payment': 'बैंक ने भुगतान के लिए ओटीपी बनाया ही नहीं',
  'The OTP was generated but the SMS was never delivered': 'ओटीपी बना था लेकिन एसएमएस नहीं पहुँचा',
  'The SMS provider is having an outage affecting delivery':
    'एसएमएस सेवा में खराबी से संदेश नहीं पहुँच रहा',
  'The processed refund has already reached the customer':
    'प्रोसेस किया गया रिफंड ग्राहक को मिल चुका है',
  'The merchant did not submit the refund': 'मर्चेंट ने रिफंड जमा नहीं किया',
  'The refund is stalled in the payment rail': 'रिफंड भुगतान प्रणाली में अटका है',
  'The refund was returned to the merchant': 'रिफंड मर्चेंट को वापस चला गया',
  'The restaurant already has the reservation': 'रेस्टोरेंट के पास रिजर्वेशन पहले से है',
  'The platform confirmation is invalid': 'प्लेटफॉर्म की पुष्टि अमान्य है',
  'The reservation failed to sync to the restaurant': 'रिजर्वेशन रेस्टोरेंट तक सिंक नहीं हुआ',
  'The restaurant record uses conflicting booking details':
    'रेस्टोरेंट रिकॉर्ड में बुकिंग विवरण अलग हैं',
  'The appointment is still recorded exactly as confirmed':
    'अपॉइंटमेंट अभी भी पुष्टि के अनुसार दर्ज है',
  'The salon deliberately cancelled the appointment': 'सैलून ने जानबूझकर अपॉइंटमेंट रद्द किया',
  'The appointment was changed incorrectly': 'अपॉइंटमेंट गलत तरीके से बदला गया',
  'The confirmed appointment failed to sync to the salon':
    'कन्फर्म अपॉइंटमेंट सैलून तक सिंक नहीं हुआ',
  'The hotel already has the booking': 'होटल के पास बुकिंग पहले से है',
  'The platform booking confirmation is invalid': 'प्लेटफॉर्म की बुकिंग पुष्टि अमान्य है',
  'The booking failed to sync to the hotel': 'बुकिंग होटल तक सिंक नहीं हुई',
  'The hotel record conflicts with the confirmed booking details':
    'होटल रिकॉर्ड और कन्फर्म बुकिंग विवरण अलग हैं',
  'General banking support': 'सामान्य बैंकिंग सहायता',
  'Refund reconciliation team': 'रिफंड मिलान टीम',
  'Restaurant reservation operations': 'रेस्टोरेंट रिजर्वेशन संचालन',
  'Appointment operations': 'अपॉइंटमेंट संचालन',
  'Hotel partner reconciliation': 'होटल साझेदार मिलान टीम',
  'Refund processed, money missing': 'रिफंड प्रोसेस हुआ, पैसा नहीं मिला',
  'Confirmed hotel booking missing': 'कन्फर्म होटल बुकिंग गायब',
  'Wrong diagnosis plus caller correction': 'गलत कारण और ग्राहक का सुधार',
  'No automated remedy remains — escalate with context':
    'स्वचालित समाधान नहीं बचा — जानकारी सहित आगे भेजें',
  'Normal OTP failure — no interruption': 'सामान्य ओटीपी विफलता — कोई रुकावट नहीं',
  'Slow tool plus interruption — the primary stress case':
    'धीमी जाँच और रुकावट — मुख्य तनाव परीक्षण',
  'OTP delivery API is down': 'ओटीपी डिलीवरी सेवा बंद है',
  'Confirmed reservation missing at restaurant': 'रेस्टोरेंट में कन्फर्म रिजर्वेशन गायब',
  'Appointment changed incorrectly': 'अपॉइंटमेंट गलत तरीके से बदला गया',
  'caller asserts this is not the cause': 'ग्राहक का कहना है कि यह कारण नहीं है',
  'caller rejected the stated diagnosis': 'ग्राहक ने बताए गए कारण को खारिज किया',
  'explicit caller request': 'ग्राहक का स्पष्ट अनुरोध',
  'caller reports no change': 'ग्राहक ने बताया कि कोई बदलाव नहीं हुआ',
  'caller reports recent successful card use': 'ग्राहक ने हाल में कार्ड सफलतापूर्वक इस्तेमाल किया',
  'caller reports the card worked recently': 'ग्राहक ने बताया कि कार्ड हाल में काम कर रहा था',
  'caller reports another payment method works':
    'ग्राहक ने बताया कि दूसरा भुगतान तरीका काम करता है',
  'caller reports no message received at all': 'ग्राहक ने बताया कि कोई संदेश नहीं मिला',
  'caller reports the last step did not help': 'ग्राहक ने बताया कि पिछला कदम काम नहीं आया',
  'caller checked their account and the credit is absent':
    'ग्राहक ने खाते में जाँच की और रकम नहीं मिली',
  'caller has a platform confirmation': 'ग्राहक के पास प्लेटफॉर्म की पुष्टि है',
  'caller has an appointment confirmation': 'ग्राहक के पास अपॉइंटमेंट की पुष्टि है',
  'caller has a hotel booking confirmation': 'ग्राहक के पास होटल बुकिंग की पुष्टि है',
  'online payments are enabled': 'ऑनलाइन भुगतान चालू हैं',
  'platform record is confirmed': 'प्लेटफॉर्म रिकॉर्ड कन्फर्म है',
  'restaurant ledger has no reservation': 'रेस्टोरेंट रिकॉर्ड में रिजर्वेशन नहीं है',
  'confirmed platform booking is missing at restaurant':
    'कन्फर्म प्लेटफॉर्म बुकिंग रेस्टोरेंट में गायब है',
  'platform booking is confirmed': 'प्लेटफॉर्म बुकिंग कन्फर्म है',
  'hotel property record is missing': 'होटल के रिकॉर्ड में बुकिंग गायब है',
  'confirmed booking is absent from hotel system': 'कन्फर्म बुकिंग होटल प्रणाली में नहीं है',
  'hotel record details conflict': 'होटल रिकॉर्ड के विवरण अलग हैं',
  'audit shows a system error': 'जाँच में सिस्टम की गलती मिली',
  ACTIVE: 'सक्रिय',
  ENABLED: 'चालू',
  DISABLED: 'बंद',
  VERIFIED: 'सत्यापित',
  UNVERIFIED: 'असत्यापित',
  GENERATED: 'बनाया गया',
  DELIVERED: 'पहुँचा',
  FAILED: 'विफल',
  CONFIRMED: 'कन्फर्म',
  MISSING: 'गायब',
  CONFLICT: 'अंतर मिला',
  STALLED: 'अटका हुआ',
  RETURNED: 'वापस गया',
  REISSUED: 'दोबारा जारी',
  REBOOKED: 'दोबारा बुक',
  CHANGED: 'बदला गया',
  CANCELLED: 'रद्द',
  SYSTEM_ERROR: 'सिस्टम की गलती',
  RECONCILED: 'मिलान पूरा',
  SUPPORTED: 'समर्थित',
  REJECTED: 'खारिज',
  RESOLVED: 'हल हुआ',
  COMPLETED: 'पूरा',
  INTERRUPTED: 'बीच में रोका गया',
  PARTIAL: 'आंशिक',
  NOT_STARTED: 'शुरू नहीं हुआ',
  FRESH: 'नया',
  RECONCILABLE: 'मिलान योग्य',
  SUPERSEDED: 'अप्रासंगिक',
  OK: 'ठीक',
  ERROR: 'त्रुटि',
  TIMEOUT: 'समय समाप्त',
  NONE: 'कोई नहीं',
  RECOMMENDED: 'सुझाया गया',
  CREATED: 'बनाया गया',
  ESCALATED: 'आगे भेजा गया',
};

const TECH_HI: Record<string, string> = {
  get_card_status: 'कार्ड स्थिति जाँच',
  get_online_transaction_status: 'ऑनलाइन भुगतान जाँच',
  get_registered_mobile_status: 'दर्ज मोबाइल जाँच',
  get_otp_generation_status: 'ओटीपी निर्माण जाँच',
  get_otp_delivery_status: 'ओटीपी डिलीवरी जाँच',
  check_refund_record: 'रिफंड रिकॉर्ड जाँच',
  trace_refund_payment: 'रिफंड भुगतान ट्रेस',
  reissue_refund: 'रिफंड दोबारा जारी करना',
  check_platform_reservation: 'प्लेटफॉर्म रिजर्वेशन जाँच',
  check_restaurant_record: 'रेस्टोरेंट रिकॉर्ड जाँच',
  rebook_reservation: 'रिजर्वेशन दोबारा बुक करना',
  check_appointment_record: 'अपॉइंटमेंट रिकॉर्ड जाँच',
  check_appointment_history: 'अपॉइंटमेंट इतिहास जाँच',
  reschedule_appointment: 'अपॉइंटमेंट फिर तय करना',
  check_platform_booking: 'प्लेटफॉर्म बुकिंग जाँच',
  check_hotel_record: 'होटल रिकॉर्ड जाँच',
  reconcile_hotel_booking: 'होटल बुकिंग मिलान',
  otp_slow_tool: 'धीमी ओटीपी जाँच',
  ecommerce_refund_missing: 'गायब ई-कॉमर्स रिफंड',
  restaurant_missing_reservation: 'गायब रेस्टोरेंट रिजर्वेशन',
  salon_appointment_changed: 'बदला हुआ सैलून अपॉइंटमेंट',
  hotel_booking_conflict: 'होटल बुकिंग में विरोधाभास',
  initial: 'प्रारंभिक',
  investigate_card: 'कार्ड की जाँच',
  investigate_online_txn: 'ऑनलाइन भुगतान की जाँच',
  investigate_contact: 'संपर्क विवरण की जाँच',
  investigate_otp_generation: 'ओटीपी बनने की जाँच',
  investigate_otp_delivery: 'ओटीपी पहुँचने की जाँच',
  investigate_refund_record: 'रिफंड रिकॉर्ड की जाँच',
  investigate_payment_rail: 'भुगतान प्रणाली की जाँच',
  investigate_reconciliation: 'रिकॉर्ड मिलान की जाँच',
  correct_appointment: 'अपॉइंटमेंट सुधार',
  escalate: 'मामला आगे भेजें',
  card_status: 'कार्ड की स्थिति',
  online_transactions: 'ऑनलाइन भुगतान',
  mobile_status: 'मोबाइल की स्थिति',
  refund_status: 'रिफंड की स्थिति',
  payment_rail_status: 'भुगतान प्रणाली की स्थिति',
  platform_booking_status: 'प्लेटफॉर्म बुकिंग की स्थिति',
  hotel_record_status: 'होटल रिकॉर्ड की स्थिति',
  platform_reservation_status: 'प्लेटफॉर्म रिजर्वेशन की स्थिति',
  restaurant_record_status: 'रेस्टोरेंट रिकॉर्ड की स्थिति',
  appointment_status: 'अपॉइंटमेंट की स्थिति',
  appointment_change_cause: 'अपॉइंटमेंट बदलाव का कारण',
};

function translateEngineText(text: string): string {
  const exact = ENGINE_HI[text];
  if (exact) return exact;
  if (text.startsWith('caller denies: ')) {
    return `ग्राहक ने खारिज किया: ${translateEngineText(text.slice('caller denies: '.length))}`;
  }
  if (text.startsWith('user correction: ')) {
    return `ग्राहक का सुधार: ${translateEngineText(text.slice('user correction: '.length))}`;
  }
  if (text.startsWith('caller asks us to investigate ')) {
    return `ग्राहक ने जाँच करने को कहा: ${text.slice('caller asks us to investigate '.length).replaceAll('_', ' ')}`;
  }
  return text;
}

type I18nValue = {
  language: UiLanguage;
  isHindi: boolean;
  t: (key: string, fallback?: string) => string;
  engineText: (value: string) => string;
  technical: (value: string) => string;
};

const FALLBACK: I18nValue = {
  language: 'english',
  isHindi: false,
  t: (_key, fallback = '') => fallback,
  engineText: (value) => value,
  technical: (value) => value,
};

const I18nContext = createContext<I18nValue>(FALLBACK);

export function I18nProvider({ language, children }: { language: string; children: ReactNode }) {
  const resolved: UiLanguage = language === 'hindi' ? 'hindi' : 'english';
  useEffect(() => {
    document.documentElement.lang = resolved === 'hindi' ? 'hi' : 'en';
    document.title = resolved === 'hindi' ? 'अनलूप वॉइस सहायता' : 'LiveKit Voice Agent';
  }, [resolved]);

  const value = useMemo<I18nValue>(() => {
    const isHindi = resolved === 'hindi';
    return {
      language: resolved,
      isHindi,
      t: (key, fallback = key) => (isHindi ? (HI[key] ?? fallback) : fallback),
      engineText: (text) => (isHindi ? translateEngineText(text) : text),
      technical: (text) =>
        isHindi ? (TECH_HI[text] ?? text.replaceAll('_', ' ').toLowerCase()) : text,
    };
  }, [resolved]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
