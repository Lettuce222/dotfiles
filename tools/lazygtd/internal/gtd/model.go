package gtd

// State is what `gtd.py json` prints.
type State struct {
	Today  string         `json:"today"`
	Root   string         `json:"root"`
	Items  []Item         `json:"items"`
	Counts map[string]int `json:"counts"`
	Broken []Broken       `json:"broken"`
}

// Broken is a file gtd.py could not read as an item.
type Broken struct {
	Path  string `json:"path"`
	Error string `json:"error"`
}

// Item is one item (one file), as gtd.py json gives it.
type Item struct {
	ID           string   `json:"id"`
	Title        string   `json:"title"`
	List         string   `json:"list"`
	Project      *string  `json:"project"`
	Actor        *string  `json:"actor"`
	Worker       *string  `json:"worker"`
	Due          *string  `json:"due"`
	Since        *string  `json:"since"`
	Done         *string  `json:"done"`
	Who          *string  `json:"who"`
	FollowUp     *string  `json:"follow_up"`
	Then         *string  `json:"then"`
	Watch        []string `json:"watch"`
	Outcome      *string  `json:"outcome"`
	Short        *string  `json:"short"`
	Steps        []string `json:"steps"`
	Links        []string `json:"links"`
	From         *string  `json:"from"`
	Source       *string  `json:"source"`
	Asked        *string  `json:"asked"`
	Answered     *string  `json:"answered"`
	Read         *string  `json:"read"`
	Body         string   `json:"body"`
	Hash         string   `json:"hash"`
	Path         string   `json:"path"`
	Deliverables []string `json:"deliverables"`
	Mine         *string  `json:"mine"`
}

// S is the value of an optional string, "" when it is absent.
func S(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// Unread tells whether the orchestrator answered later than the user read (desk/talk.mjs).
func (it *Item) Unread() bool {
	a := S(it.Answered)
	return a != "" && S(it.Read) < a
}

// Waiting tells whether the user asked later than the orchestrator answered.
func (it *Item) Waiting() bool {
	q := S(it.Asked)
	return q != "" && S(it.Answered) < q
}

// IsAgent tells whether an agent does the item.
func (it *Item) IsAgent() bool { return S(it.Actor) == "agent" || S(it.Worker) != "" }
