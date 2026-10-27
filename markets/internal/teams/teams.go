// Package teams tells whether two venues' team names are the same team.
//
// Venues name teams differently: "Chelsea", "Chelsea FC"; "Bilbao", "Athletic
// Club", "Athletic Club Bilbao"; "Santander", "Real Racing Club". A name is
// reduced to a key (accents, case, punctuation, founding years and filler
// words like FC, Club or Spor Kulübü dropped, then a few known aliases applied), and two names match when
// their keys are equal or one's words are all in the other's ("Tottenham",
// "Tottenham Hotspur"), unless that one word could be several teams
// ("Manchester", "Real").
package teams

import (
	"slices"
	"strings"
	"unicode"

	"golang.org/x/text/runes"
	"golang.org/x/text/transform"
	"golang.org/x/text/unicode/norm"
)

// filler words that say nothing about which team it is.
var filler = map[string]bool{
	"fc": true, "afc": true, "cf": true, "cd": true, "ud": true, "rcd": true, "rc": true,
	"sd": true, "ca": true, "sc": true, "club": true, "de": true, "del": true, "la": true,
	"el": true, "a": true, "futbol": true, "balompie": true, "and": true, "the": true,
	"hove": true, "albion": true, "reial": true, "deportiu": true,
	// European clubs' prefixes and suffixes (Champions League).
	"sk": true, "fk": true, "bv": true, "ssc": true, "as": true, "ac": true, "osc": true,
	"kv": true, "spor": true, "kulubu": true, "calcio": true, "vfb": true, "vfl": true,
	"sv": true, "tsg": true, "ogc": true, "fsv": true,
}

// aliases maps a key to the key the other venues use.
var aliases = map[string]string{
	"bilbao":                  "athletic",
	"athletic bilbao":         "athletic",
	"real racing":             "racing santander",
	"santander":               "racing santander",
	"real racing santander":   "racing santander",
	"racing":                  "racing santander",
	"espanyol barcelona":      "espanyol",
	"real celta vigo":         "celta vigo",
	"celta":                   "celta vigo",
	"vallecano":               "rayo vallecano",
	"rayo vallecano madrid":   "rayo vallecano",
	"atletico":                "atletico madrid",
	"deportivo coruna":        "deportivo",
	"deportivo alaves":        "alaves",
	"man city":                "manchester city",
	"man united":              "manchester united",
	"man utd":                 "manchester united",
	"spurs":                   "tottenham",
	"tottenham hotspur":       "tottenham",
	"wolves":                  "wolverhampton",
	"wolverhampton wanderers": "wolverhampton",
	"nottm forest":            "nottingham forest",
	"newcastle united":        "newcastle",
	"west ham united":         "west ham",
	"brighton":                "brighton",
	// MLS: the two Los Angeles teams must stay apart.
	"los angeles":            "lafc",
	"lafc":                   "lafc",
	"galaxy":                 "la galaxy",
	"los angeles galaxy":     "la galaxy",
	"red bull new york":      "new york red bulls",
	"ny red bulls":           "new york red bulls",
	"new york rb":            "new york red bulls",
	"red bulls":              "new york red bulls",
	"nycfc":                  "new york city",
	"new york city football": "new york city",
	"ny city":                "new york city",
	"d c united":             "dc united",
	"atlanta united":         "atlanta",
	"orlando city":           "orlando",
	"philadelphia union":     "philadelphia",
	"new england revolution": "new england",
	"seattle sounders":       "seattle",
	"portland timbers":       "portland",
	"sporting kansas city":   "kansas city",
	"sporting kc":            "kansas city",
	"inter miami":            "miami",
	"montreal":               "cf montreal",
	"foot montreal":          "cf montreal",
	"minnesota united":       "minnesota",
	"vancouver whitecaps":    "vancouver",
	"houston dynamo":         "houston",
	"colorado rapids":        "colorado",
	"san jose earthquakes":   "san jose",
	"st louis city":          "st louis",
	"saint louis":            "st louis",
	"real salt lake":         "salt lake",
	"los angeles f":          "lafc",
	"los angeles g":          "la galaxy",
	"columbus crew":          "columbus",
	"chicago fire":           "chicago",
	// Champions League
	"psg":                        "paris saint germain",
	"paris sg":                   "paris saint germain",
	"internazionale milano":      "inter",
	"internazionale":             "inter",
	"inter milan":                "inter",
	"lask linz":                  "lask",
	"linzer athletik sport klub": "lask",
	"slavia praha":               "slavia prague",
	"bayern munchen":             "bayern munich",
	"rasenballsport leipzig":     "rb leipzig",
	"psv eindhoven":              "psv",
	"eindhoven":                  "psv",
	"sporting clube portugal":    "sporting cp",
	"sporting lisbon":            "sporting cp",
	"bodoe glimt":                "bodo glimt",
	// Bundesliga
	"m gladbach":                   "borussia monchengladbach",
	"mgladbach":                    "borussia monchengladbach",
	"gladbach":                     "borussia monchengladbach",
	"monchengladbach":              "borussia monchengladbach",
	"borussia vfl monchengladbach": "borussia monchengladbach",
	"hamburger":                    "hamburg",
	"cologne":                      "koln",
}

// letters that don't decompose into a base letter and an accent.
var letters = strings.NewReplacer("ø", "o", "Ø", "O", "æ", "ae", "Æ", "AE", "ß", "ss", "ł", "l", "Ł", "L", "đ", "d", "Đ", "D", "ı", "i")

// ambiguous single words: several teams' names contain them.
var ambiguous = map[string]bool{
	"manchester": true, "real": true, "united": true, "city": true, "madrid": true,
	"sporting": true, "inter": true,
}

// Key reduces a team name to the form names are compared in.
func Key(name string) string {
	t := transform.Chain(norm.NFD, runes.Remove(runes.In(unicode.Mn)), norm.NFC)
	s, _, err := transform.String(t, letters.Replace(name))
	if err != nil {
		s = name
	}
	s = strings.ToLower(s)
	var words []string
	for _, w := range strings.FieldsFunc(s, func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) }) {
		// Founding years ("VfB Stuttgart 1893", "Borussia 09 Dortmund") are filler too.
		if !filler[w] && strings.TrimFunc(w, unicode.IsDigit) != "" {
			words = append(words, w)
		}
	}
	key := strings.Join(words, " ")
	if a, ok := aliases[key]; ok {
		return a
	}
	return key
}

// Same reports whether two names are the same team.
func Same(a, b string) bool {
	ka, kb := Key(a), Key(b)
	if ka == "" || kb == "" {
		return false
	}
	if ka == kb {
		return true
	}
	wa, wb := strings.Fields(ka), strings.Fields(kb)
	if len(wa) > len(wb) {
		wa, wb = wb, wa
	}
	if len(wa) == 1 && ambiguous[wa[0]] {
		return false
	}
	for _, w := range wa {
		if !slices.Contains(wb, w) {
			return false
		}
	}
	return true
}
