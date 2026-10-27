package teams

import "testing"

// The same team as Kalshi, Polymarket US and Novig name it (Oct 2026).
var sameTeams = [][]string{
	{"Chelsea", "Chelsea FC", "Chelsea FC"},
	{"Tottenham", "Tottenham Hotspur FC", "Tottenham Hotspur FC"},
	{"Brighton", "Brighton & Hove Albion FC", "Brighton & Hove Albion FC"},
	{"Bournemouth", "AFC Bournemouth", "AFC Bournemouth"},
	{"Manchester United", "Manchester United FC", "Manchester United FC"},
	{"Manchester City", "Manchester City FC", "Manchester City FC"},
	{"Newcastle", "Newcastle United FC", "Newcastle United FC"},
	{"Leeds United", "Leeds United FC", "Leeds United FC"},
	{"Hull City", "Hull City AFC", "Hull City AFC"},
	{"Coventry", "Coventry City FC", "Coventry City FC"},
	{"Nottingham Forest", "Nottingham Forest FC", "Nottm Forest"},
	{"Bilbao", "Athletic Club", "Athletic Club Bilbao"},
	{"Atletico", "Club Atletico de Madrid", "Club Atlético de Madrid"},
	{"Deportivo De La Coruna", "RC Deportivo A Coruna", "RC Deportivo de La Coruña"},
	{"Celta Vigo", "RC Celta de Vigo", "Real Club Celta de Vigo"},
	{"Real Betis", "Real Betis Balompie", "Real Betis Balompié", "Real Betis Seville"},
	{"Real Sociedad", "Real Sociedad de Futbol", "Real Sociedad de Fútbol"},
	{"Espanyol", "RCD Espanyol de Barcelona", "Reial Club Deportiu Espanyol"},
	{"Santander", "Real Racing Club", "Real Racing Club de Santander"},
	{"Vallecano", "Rayo Vallecano de Madrid", "Rayo Vallecano"},
	{"Alaves", "Deportivo Alaves", "Deportivo Alavés"},
	{"Osasuna", "CA Osasuna", "CA Osasuna"},
	{"Real Madrid", "Real Madrid CF", "Real Madrid CF"},
	{"Barcelona", "FC Barcelona", "FC Barcelona"},
	{"Levante", "Levante UD", "Levante UD"},
	// MLS
	{"Atlanta", "Atlanta United FC", "Atlanta United FC"},
	{"Austin", "Austin FC", "Austin FC"},
	{"Charlotte", "Charlotte FC", "Charlotte FC"},
	{"Chicago Fire", "Chicago Fire FC", "Chicago Fire FC"},
	{"Cincinnati", "FC Cincinnati", "FC Cincinnati"},
	{"Colorado", "Colorado Rapids SC", "Colorado Rapids"},
	{"Columbus", "Columbus Crew", "Columbus Crew"},
	{"Dallas", "FC Dallas", "FC Dallas"},
	{"DC United", "D.C. United SC", "DC United"},
	{"Houston", "Houston Dynamo", "Houston Dynamo FC"},
	{"Los Angeles F", "Los Angeles FC", "Los Angeles FC"},
	{"Los Angeles G", "Los Angeles Galaxy", "LA Galaxy"},
	{"Miami", "Inter Miami CF", "Inter Miami CF"},
	{"Minnesota", "Minnesota United FC", "Minnesota United FC"},
	{"Montreal", "CF Montreal", "CF Montréal"},
	{"Nashville", "Nashville SC", "Nashville SC"},
	{"New England", "New England Revolution", "New England Revolution"},
	{"New York City", "New York City FC", "New York City Football Club"},
	{"New York RB", "New York Red Bulls", "New York Red Bulls"},
	{"Orlando", "Orlando City SC", "Orlando City SC"},
	{"Philadelphia", "Philadelphia Union", "Philadelphia Union"},
	{"Portland", "Portland Timbers", "Portland Timbers"},
	{"Salt Lake", "Real Salt Lake", "Real Salt Lake"},
	{"San Diego FC", "San Diego FC", "San Diego FC"},
	{"San Jose", "San Jose Earthquakes", "San Jose Earthquakes"},
	{"Seattle", "Seattle Sounders FC", "Seattle Sounders FC"},
	{"Kansas City", "Sporting Kansas City", "Sporting Kansas City"},
	{"Saint Louis", "St. Louis City SC", "St. Louis City SC"},
	{"Toronto", "Toronto FC", "Toronto FC"},
	{"Vancouver", "Vancouver Whitecaps FC", "Vancouver Whitecaps FC"},
	// Champions League (Nov 2026)
	{"Shakhtar", "FC Shakhtar Donetsk", "FC Shakhtar Donetsk"},
	{"Sporting CP", "Sporting CP", "Sporting Clube de Portugal"},
	{"Galatasaray", "Galatasaray SK", "Galatasaray Spor Kulübü"},
	{"Stuttgart", "VfB Stuttgart", "VfB Stuttgart 1893"},
	{"Bayern Munich", "FC Bayern München", "FC Bayern München"},
	{"Aston Villa", "Aston Villa", "Aston Villa FC"},
	{"Bodoe/Glimt", "FK Bodø/Glimt", "FK Bodø / Glimt"},
	{"Lille", "Lille OSC", "Lille OSC"},
	{"Feyenoord", "Feyenoord Rotterdam", "Feyenoord Rotterdam"},
	{"Inter", "FC Internazionale Milano", "FC Internazionale Milano"},
	{"LASK", "LASK Linz", "Linzer Athletik Sport Klub"},
	{"Slovan Bratislava", "ŠK Slovan Bratislava", "ŠK Slovan Bratislava"},
	{"Roma", "AS Roma", "AS Roma"},
	{"Villarreal", "Villarreal", "Villarreal CF"},
	{"PSG", "Paris Saint-Germain", "Paris Saint-Germain FC"},
	{"AEK Athens", "AEK", "AEK Athens FC"},
	{"Fenerbahce", "Fenerbahçe SK", "Fenerbahçe Spor Kulübü"},
	{"Liverpool", "Liverpool", "Liverpool FC"},
	{"Dortmund", "BV Borussia 09 Dortmund", "BV Borussia 09 Dortmund"},
	{"Porto", "FC Porto", "FC Porto"},
	{"Napoli", "SSC Napoli", "SSC Napoli"},
	{"Eindhoven", "PSV", "PSV Eindhoven"},
	{"Club Brugge", "Club Brugge KV", "Club Brugge KV"},
	{"Leipzig", "RB Leipzig", "RasenBallsport Leipzig"},
	{"Lens", "Racing Club de Lens", "Racing Club de Lens"},
	{"Como", "Como 1907", "Calcio Como 1907"},
	{"Slavia Prague", "SK Slavia Praha", "SK Slavia Praha"},
	{"Arsenal", "Arsenal", "Arsenal FC"},
	{"Viking", "Viking FK", "Viking FK"},
	{"Sabah Masazir", "Sabah FK", "Sabah FK"},
}

func TestTheVenuesNamesForATeamMatch(t *testing.T) {
	for _, names := range sameTeams {
		for i := range names {
			for j := range names {
				if !Same(names[i], names[j]) {
					t.Errorf("%q and %q should be the same team (keys %q, %q)", names[i], names[j], Key(names[i]), Key(names[j]))
				}
			}
		}
	}
}

func TestDifferentTeamsDontMatch(t *testing.T) {
	for i, a := range sameTeams {
		for j, b := range sameTeams {
			if i == j {
				continue
			}
			for _, x := range a {
				for _, y := range b {
					if Same(x, y) {
						t.Errorf("%q and %q matched (keys %q, %q)", x, y, Key(x), Key(y))
					}
				}
			}
		}
	}
	for _, pair := range [][2]string{
		{"Manchester", "Manchester United"},
		{"Real", "Real Madrid"},
		{"Real Madrid", "Real Sociedad"},
		{"Espanyol", "Barcelona"},
		{"Inter", "Inter Miami CF"},
		{"Sporting CP", "Sporting Kansas City"},
		{"Racing Club de Lens", "Real Racing Club de Santander"},
		{"", ""},
	} {
		if Same(pair[0], pair[1]) {
			t.Errorf("%q and %q matched", pair[0], pair[1])
		}
	}
}

func TestKey(t *testing.T) {
	for name, want := range map[string]string{
		"Brighton & Hove Albion FC": "brighton",
		"Club Atlético de Madrid":   "atletico madrid",
		"RC Deportivo A Coruna":     "deportivo",
		"Tottenham Hotspur FC":      "tottenham",
		"VfB Stuttgart 1893":        "stuttgart",
		"FK Bodø / Glimt":           "bodo glimt",
		"Galatasaray Spor Kulübü":   "galatasaray",
	} {
		if got := Key(name); got != want {
			t.Errorf("Key(%q) = %q, want %q", name, got, want)
		}
	}
}
