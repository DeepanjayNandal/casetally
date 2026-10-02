"""Document frequency of the most common lexemes in the corpus, as a percentage
of current chunks.

Generated, not hand written. Regenerate after any change to the corpus with:

    SELECT word, round((100.0*ndoc/<total_current_chunks>)::numeric, 2)
    FROM ts_stat('SELECT search_vector FROM legal_chunks WHERE is_current')
    WHERE 100.0*ndoc/<total_current_chunks> >= 5.0
    ORDER BY ndoc DESC;

Only lexemes at or above 5% are listed, which is the lowest threshold the
lexical branch can be tuned to without a rebuild. Anything absent from this map
is rarer than that and is always kept.

Measured against 83,706 current chunks.
"""

COMMON_LEXEME_PCT = {
    "shall": 80.69, "section": 71.29, "b": 68.89, "1": 67.65, "2": 63.78, "may": 59.84,
    "c": 54.45, "state": 53.86, "titl": 53.31, "note": 52.95, "provid": 50.96, "relat": 49.98,
    "3": 49.93, "secretari": 49.00, "includ": 47.09, "subsect": 46.32, "requir": 43.18,
    "editori": 43.12, "d": 40.49, "effect": 40.31, "date": 39.23, "purpos": 38.96,
    "author": 38.32, "determin": 37.37, "unit": 37.25, "general": 36.82, "paragraph": 35.89,
    "use": 35.56, "year": 35.24, "appropri": 35.19, "4": 34.75, "provis": 34.70,
    "amend": 34.43, "servic": 31.99, "statutori": 31.86, "5": 31.73, "subsidiari": 31.39,
    "applic": 31.38, "feder": 30.98, "ii": 30.68, "respect": 30.48, "establish": 29.42,
    "refer": 29.02, "term": 28.96, "e": 28.78, "made": 27.98, "describ": 27.56, "law": 26.81,
    "act": 26.35, "person": 26.19, "program": 26.14, "chapter": 25.28, "except": 25.11,
    "agenc": 24.99, "public": 24.93, "amount": 24.81, "regul": 24.44, "time": 23.93,
    "subject": 23.80, "make": 23.46, "avail": 23.10, "within": 23.09, "carri": 22.94,
    "pursuant": 22.48, "period": 22.23, "inform": 22.23, "fund": 22.05, "nation": 21.99,
    "administr": 21.95, "mean": 21.86, "case": 21.84, "receiv": 21.55, "necessari": 21.52,
    "appli": 21.18, "activ": 20.68, "report": 20.53, "subparagraph": 20.42, "f": 20.28,
    "part": 20.19, "offic": 20.19, "govern": 19.94, "develop": 19.73, "iii": 19.54,
    "accord": 19.47, "assist": 19.35, "oper": 19.26, "individu": 19.25, "day": 19.12,
    "subchapt": 18.55, "6": 18.42, "limit": 17.99, "reason": 17.95, "plan": 17.68,
    "text": 17.32, "otherwis": 17.05, "submit": 16.96, "interest": 16.95, "design": 16.89,
    "follow": 16.78, "upon": 16.63, "order": 16.56, "depart": 16.53, "prior": 16.29,
    "cost": 16.18, "extent": 15.87, "issu": 15.75, "payment": 15.43, "prescrib": 15.17,
    "later": 14.91, "addit": 14.90, "grant": 14.86, "defin": 14.78, "secur": 14.69,
    "action": 14.59, "7": 14.22, "organ": 14.15, "direct": 14.12, "g": 14.11, "conduct": 14.11,
    "rule": 13.65, "condit": 13.57, "approv": 13.56, "one": 13.45, "elig": 13.40,
    "agreement": 13.34, "consid": 13.25, "base": 13.19, "without": 13.19, "10": 13.02,
    "system": 13.01, "regard": 12.96, "manner": 12.87, "meet": 12.85, "account": 12.76,
    "employe": 12.62, "transfer": 12.61, "u.s.c": 12.60, "member": 12.57, "repres": 12.56,
    "manag": 12.51, "less": 12.43, "would": 12.43, "fiscal": 12.37, "congress": 12.22,
    "local": 12.18, "result": 12.16, "exceed": 12.12, "entiti": 12.06, "basi": 12.04,
    "unless": 12.02, "practic": 11.98, "perform": 11.93, "codif": 11.88, "health": 11.88,
    "contract": 11.85, "support": 11.81, "execut": 11.77, "particip": 11.76,
    "implement": 11.74, "request": 11.73, "iv": 11.69, "respons": 11.69, "take": 11.59,
    "revis": 11.59, "area": 11.55, "review": 11.53, "protect": 11.49, "sourc": 11.40,
    "facil": 11.37, "function": 11.31, "benefit": 11.31, "institut": 11.01, "procedur": 10.99,
    "consist": 10.98, "specifi": 10.97, "whether": 10.95, "000": 10.90, "educ": 10.86,
    "committe": 10.77, "notic": 10.74, "right": 10.63, "histor": 10.60, "consult": 10.58,
    "8": 10.58, "control": 10.56, "project": 10.50, "standard": 10.48, "ensur": 10.43,
    "need": 10.41, "enter": 10.38, "employ": 10.38, "properti": 10.37, "code": 10.31,
    "annual": 10.30, "h": 10.25, "contain": 10.20, "exist": 10.17, "product": 10.14,
    "definit": 10.11, "30": 10.09, "pay": 10.09, "thereof": 9.99, "percent": 9.93,
    "serv": 9.87, "director": 9.80, "improv": 9.71, "claus": 9.70, "number": 9.68,
    "hous": 9.65, "notwithstand": 9.65, "duti": 9.62, "identifi": 9.56, "process": 9.55,
    "involv": 9.54, "continu": 9.52, "rate": 9.48, "commiss": 9.47, "begin": 9.42,
    "document": 9.41, "maintain": 9.40, "special": 9.29, "find": 9.29, "privat": 9.28,
    "paid": 9.24, "court": 9.19, "busi": 9.07, "cover": 9.04, "polici": 9.04, "financi": 8.98,
    "affect": 8.93, "concern": 8.93, "month": 8.89, "deem": 8.82, "locat": 8.82,
    "construct": 8.80, "corpor": 8.78, "foreign": 8.73, "enforc": 8.65, "presid": 8.65,
    "resourc": 8.64, "land": 8.63, "file": 8.58, "set": 8.56, "chang": 8.49, "associ": 8.45,
    "stat": 8.44, "termin": 8.39, "assess": 8.38, "specif": 8.35, "board": 8.35, "l": 8.35,
    "coordin": 8.31, "increas": 8.29, "first": 8.28, "equal": 8.26, "proceed": 8.23,
    "statut": 8.23, "certain": 8.23, "collect": 8.23, "record": 8.20, "train": 8.18,
    "transport": 8.16, "permit": 8.05, "allow": 8.04, "15": 8.02, "complet": 8.02,
    "jurisdict": 7.98, "9": 7.93, "qualifi": 7.93, "research": 7.89, "connect": 7.88,
    "12": 7.84, "prevent": 7.82, "district": 7.79, "intern": 7.77, "credit": 7.73,
    "total": 7.71, "work": 7.70, "oblig": 7.64, "form": 7.47, "new": 7.47, "propos": 7.45,
    "preced": 7.42, "larg": 7.42, "data": 7.40, "et": 7.38, "seq": 7.36, "cooper": 7.34,
    "initi": 7.33, "obtain": 7.32, "end": 7.32, "u.s": 7.31, "access": 7.26, "prohibit": 7.26,
    "violat": 7.24, "recommend": 7.23, "least": 7.19, "insur": 7.17, "parti": 7.17,
    "defens": 7.17, "v": 7.15, "materi": 7.12, "reduc": 7.10, "opportun": 7.07, "place": 7.04,
    "expens": 6.99, "natur": 6.94, "valu": 6.89, "purchas": 6.83, "evalu": 6.83, "incom": 6.79,
    "name": 6.78, "noth": 6.77, "certif": 6.74, "personnel": 6.69, "technolog": 6.68,
    "caus": 6.68, "communiti": 6.66, "entitl": 6.66, "sale": 6.60, "care": 6.51,
    "administ": 6.49, "complianc": 6.49, "level": 6.48, "written": 6.48, "appoint": 6.46,
    "offici": 6.43, "given": 6.41, "senat": 6.40, "consider": 6.36, "engag": 6.36, "31": 6.33,
    "compens": 6.31, "compli": 6.31, "market": 6.31, "award": 6.29, "impos": 6.26,
    "sentenc": 6.25, "distribut": 6.22, "share": 6.17, "similar": 6.12, "forc": 6.10,
    "claim": 6.07, "taken": 6.07, "charg": 6.06, "treatment": 6.04, "final": 6.03,
    "promot": 5.99, "safeti": 5.97, "remain": 5.92, "accept": 5.92, "demonstr": 5.90,
    "technic": 5.88, "prepar": 5.84, "reserv": 5.82, "treat": 5.82, "substanti": 5.81,
    "attorney": 5.81, "20": 5.78, "fee": 5.77, "civil": 5.76, "power": 5.75, "full": 5.74,
    "statement": 5.72, "contribut": 5.68, "pub": 5.67, "matter": 5.64, "select": 5.61,
    "relev": 5.61, "loan": 5.59, "acquir": 5.58, "countri": 5.56, "adjust": 5.56,
    "advanc": 5.56, "econom": 5.55, "energi": 5.54, "portion": 5.54, "anoth": 5.54,
    "sum": 5.50, "treasuri": 5.49, "resid": 5.49, "tax": 5.47, "constru": 5.47, "11": 5.46,
    "publish": 5.46, "50": 5.44, "18": 5.43, "measur": 5.41, "agricultur": 5.41, "group": 5.36,
    "decemb": 5.36, "emerg": 5.35, "util": 5.33, "address": 5.32, "investig": 5.30,
    "medic": 5.26, "forth": 5.24, "maximum": 5.23, "water": 5.22, "elect": 5.21, "among": 5.21,
    "studi": 5.18, "furnish": 5.17, "occur": 5.16, "excess": 5.13, "certifi": 5.13,
    "either": 5.12, "current": 5.12, "42": 5.12, "receipt": 5.08, "per": 5.07, "method": 5.07,
    "equip": 5.07, "exempt": 5.03, "trade": 5.02, "risk": 5.01, "non": 5.01,
}
