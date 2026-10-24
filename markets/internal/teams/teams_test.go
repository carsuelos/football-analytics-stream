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
	{"Real Betis", "Real Betis Balompie", "Real Betis Balompié"},
	{"Real Sociedad", "Real Sociedad de Futbol", "Real Sociedad de Fútbol"},
	{"Espanyol", "RCD Espanyol de Barcelona", "Reial Club Deportiu Espanyol"},
	{"Santander", "Real Racing Club", "Real Racing Club de Santander"},
	{"Vallecano", "Rayo Vallecano de Madrid", "Rayo Vallecano"},
	{"Alaves", "Deportivo Alaves", "Deportivo Alavés"},
	{"Osasuna", "CA Osasuna", "CA Osasuna"},
	{"Real Madrid", "Real Madrid CF", "Real Madrid CF"},
	{"Barcelona", "FC Barcelona", "FC Barcelona"},
	{"Levante", "Levante UD", "Levante UD"},
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
	} {
		if got := Key(name); got != want {
			t.Errorf("Key(%q) = %q, want %q", name, got, want)
		}
	}
}
