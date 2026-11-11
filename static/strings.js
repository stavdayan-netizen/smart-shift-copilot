/* All user-facing copy, in one place (natural, gender-neutral Hebrew). The product name stays in English.
   After the assignment below this is plain JSON, so tests/test_ui_shell.py can parse and lint every string. */
window.T = {
  "app": {
    "name": "Smart Shift Copilot",
    "demoNote": "מערכת הדגמה עם נתונים מדומים בלבד.",
    "skip": "דילוג לתוכן הראשי"
  },
  "login": {
    "title": "כניסה למערכת",
    "intro": "אפשר להיכנס עם השם וקוד הגישה האישי.",
    "name": "שם",
    "code": "קוד גישה",
    "codeHint": "למנהל/ת: כאן מזינים את הסיסמה.",
    "submit": "כניסה",
    "submitting": "נכנסים…",
    "showCode": "הצגת הקוד",
    "hideCode": "הסתרת הקוד",
    "missing": "יש למלא שם וקוד גישה.",
    "wrong": "השם או קוד הגישה שגויים.",
    "blocked": "יותר מדי ניסיונות כושלים. אפשר לנסות שוב בעוד {minutes} דקות.",
    "expired": "פג תוקף ההתחברות. יש להיכנס מחדש.",
    "loggedOut": "התנתקתם בהצלחה."
  },
  "errors": {
    "network": "אין חיבור לשרת. כדאי לנסות שוב בעוד רגע.",
    "forbidden": "אין הרשאה לפעולה הזו.",
    "invalid": "חלק מהפרטים חסרים או לא תקינים.",
    "generic": "משהו השתבש. אפשר לנסות שוב.",
    "limit": "הגעתם למגבלת ההודעות. אפשר לנסות שוב מאוחר יותר."
  },
  "nav": {
    "label": "ניווט ראשי",
    "home": "בית",
    "assistant": "העוזר החכם",
    "account": "החשבון שלי"
  },
  "role": {
    "manager": "מנהל/ת",
    "employee": "עובד/ת"
  },
  "home": {
    "title": "שלום, {name}",
    "lead": "המסך הזה עדיין בבנייה.",
    "body": "בהמשך אפשר יהיה להגיש כאן זמינות למשמרות ולראות את הסידור האישי."
  },
  "assistant": {
    "title": "העוזר החכם",
    "who": "העוזר החכם",
    "emptyTitle": "אפשר להתחיל שיחה",
    "emptyBody": "העוזר עדיין לא מחובר לנתוני המשמרות, ולכן אי אפשר לשאול אותו על הסידור. כלי הנתונים יתווספו בהמשך.",
    "placeholder": "כתבו הודעה…",
    "send": "שליחה",
    "newChat": "שיחה חדשה",
    "history": "שיחות",
    "thinking": "העוזר חושב…",
    "usingTool": "בודק נתונים…",
    "details": "פרטים טכניים",
    "toolStart": "מתחיל",
    "toolDone": "הסתיים",
    "tokens": "קלט {input} · פלט {output} · עלות משוערת ${cost}",
    "youLabel": "אתם",
    "errorPrefix": "שגיאה",
    "tooLong": "ההודעה ארוכה מדי.",
    "tableLabel": "טבלה"
  },
  "history": {
    "title": "שיחות קודמות",
    "close": "סגירה",
    "loading": "טוענים שיחות…",
    "empty": "אין שיחות קודמות עדיין.",
    "failed": "לא הצלחנו לטעון את השיחות.",
    "retry": "ניסיון חוזר",
    "untitled": "שיחה ללא כותרת"
  },
  "account": {
    "title": "החשבון שלי",
    "name": "שם",
    "role": "תפקיד",
    "logout": "התנתקות",
    "loggingOut": "מתנתקים…",
    "about": "אודות",
    "aboutBody": "גרסת הדגמה לקורס, עם נתונים מדומים בלבד.",
    "legalTitle": "הודעה משפטית",
    "legal": "המערכת אינה מיישמת את דרישות דיני העבודה בישראל, כמו מנוחה שבועית, מגבלות שעות עבודה ושעות נוספות. נדרשים פיתוח נוסף וייעוץ משפטי לפני כל שימוש עם עובדים אמיתיים.",
    "legalLink": "הודעה משפטית",
    "ok": "הבנתי"
  },
  "status": {
    "loading": "טוענים…",
    "retry": "ניסיון חוזר"
  }
};
