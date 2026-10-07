package statsbomb

// Raw StatsBomb JSON shapes. Only the fields we use are declared; encoding/json
// ignores the rest. These types are unexported: nothing outside this package
// ever sees provider data.

// named is StatsBomb's ubiquitous {"id": ..., "name": ...} object.
type named struct {
	ID   int    `json:"id"`
	Name string `json:"name"`
}

// withOutcome covers event details whose only field we need is the outcome.
type withOutcome struct {
	Outcome *named `json:"outcome"`
}

type rawEvent struct {
	ID             string    `json:"id"`
	Index          int       `json:"index"`
	Period         int       `json:"period"`
	Timestamp      string    `json:"timestamp"` // "HH:MM:SS.mmm", relative to the period start
	Type           named     `json:"type"`
	Possession     int       `json:"possession"`
	PossessionTeam named     `json:"possession_team"`
	Team           *named    `json:"team"`
	Player         *named    `json:"player"`
	Location       []float64 `json:"location"`

	Pass *struct {
		EndLocation []float64 `json:"end_location"`
		Outcome     *named    `json:"outcome"` // absent means the pass was completed
	} `json:"pass"`
	Carry *struct {
		EndLocation []float64 `json:"end_location"`
	} `json:"carry"`
	Shot *struct {
		XG          float64   `json:"statsbomb_xg"`
		EndLocation []float64 `json:"end_location"` // [x, y] or [x, y, z]
		Outcome     *named    `json:"outcome"`
	} `json:"shot"`
	Duel *struct {
		Type    *named `json:"type"`
		Outcome *named `json:"outcome"`
	} `json:"duel"`
	BallReceipt  *withOutcome `json:"ball_receipt"`
	Dribble      *withOutcome `json:"dribble"`
	Interception *withOutcome `json:"interception"`
	FiftyFifty   *withOutcome `json:"50_50"`
}

type rawMatch struct {
	MatchID     int    `json:"match_id"`
	MatchDate   string `json:"match_date"`
	HomeScore   int    `json:"home_score"`
	AwayScore   int    `json:"away_score"`
	Competition struct {
		Name string `json:"competition_name"`
	} `json:"competition"`
	Season struct {
		Name string `json:"season_name"`
	} `json:"season"`
	Stage struct {
		Name string `json:"name"`
	} `json:"competition_stage"`
	HomeTeam struct {
		ID   int    `json:"home_team_id"`
		Name string `json:"home_team_name"`
	} `json:"home_team"`
	AwayTeam struct {
		ID   int    `json:"away_team_id"`
		Name string `json:"away_team_name"`
	} `json:"away_team"`
}
