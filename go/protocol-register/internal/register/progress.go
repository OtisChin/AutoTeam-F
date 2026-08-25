package register

import "autoteam-f/protocol-register/internal/model"

type Progress struct{ events []model.Event }

func (p *Progress) Add(stage, message string, extra map[string]any) {
	p.events = append(p.events, model.Event{Stage: stage, Message: message, Extra: extra})
}

func (p *Progress) Events() []model.Event {
	out := make([]model.Event, len(p.events))
	copy(out, p.events)
	return out
}
