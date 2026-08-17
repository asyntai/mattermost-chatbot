package main

import (
	"fmt"
	"strconv"
	"strings"
	"sync"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/plugin"
)

const (
	commandTrigger = "asyntai"
	botUsername    = "asyntai"
	botDisplayName = "Asyntai"
	botDescription = "Answers questions from your own content."

	// Marks a post this plugin created on a person's behalf, so it is never
	// treated as a new question.
	echoProp = "asyntai_echo"
)

type configuration struct {
	APIKey              string
	WebsiteID           string
	AllowDirectMessages bool
	APIBaseURL          string
}

// websiteID returns the configured website, or 0 to let Asyntai pick the
// primary one. A value that is not a number is treated as not set.
func (c *configuration) websiteID() int {
	id, err := strconv.Atoi(strings.TrimSpace(c.WebsiteID))
	if err != nil || id < 0 {
		return 0
	}
	return id
}

type Plugin struct {
	plugin.MattermostPlugin

	lock          sync.RWMutex
	configuration *configuration
	botUserID     string
}

func (p *Plugin) getConfiguration() *configuration {
	p.lock.RLock()
	defer p.lock.RUnlock()

	if p.configuration == nil {
		return &configuration{}
	}
	return p.configuration
}

func (p *Plugin) OnConfigurationChange() error {
	var cfg configuration
	if err := p.API.LoadPluginConfiguration(&cfg); err != nil {
		return fmt.Errorf("could not load the plugin configuration: %w", err)
	}

	p.lock.Lock()
	p.configuration = &cfg
	p.lock.Unlock()

	return nil
}

func (p *Plugin) OnActivate() error {
	botID, err := p.API.EnsureBotUser(&model.Bot{
		Username:    botUsername,
		DisplayName: botDisplayName,
		Description: botDescription,
	})
	if err != nil {
		return fmt.Errorf("could not create the Asyntai bot account: %w", err)
	}
	p.botUserID = botID

	if err := p.API.RegisterCommand(&model.Command{
		Trigger:          commandTrigger,
		AutoComplete:     true,
		AutoCompleteDesc: "Ask Asyntai a question",
		AutoCompleteHint: "[your question]",
		DisplayName:      botDisplayName,
		Description:      botDescription,
	}); err != nil {
		return fmt.Errorf("could not register the /%s command: %w", commandTrigger, err)
	}

	return nil
}

func (p *Plugin) client() *asyntaiClient {
	cfg := p.getConfiguration()
	return newAsyntaiClient(cfg.APIBaseURL, cfg.APIKey)
}

// ExecuteCommand answers /asyntai <question>.
func (p *Plugin) ExecuteCommand(_ *plugin.Context, args *model.CommandArgs) (*model.CommandResponse, *model.AppError) {
	question := strings.TrimSpace(strings.TrimPrefix(args.Command, "/"+commandTrigger))

	if question == "" {
		return &model.CommandResponse{
			ResponseType: model.CommandResponseTypeEphemeral,
			Text:         "Ask a question, for example `/asyntai how do I reset my password`.",
		}, nil
	}

	cfg := p.getConfiguration()
	if strings.TrimSpace(cfg.APIKey) == "" {
		return &model.CommandResponse{
			ResponseType: model.CommandResponseTypeEphemeral,
			Text:         "Asyntai is not set up yet. A system administrator needs to add the API key in System Console, Plugins, Asyntai AI Chatbot.",
		}, nil
	}

	// One conversation per channel and user, so follow up questions keep context.
	sessionID := "mm_" + args.ChannelId + "_" + args.UserId

	answer, err := p.client().ask(question, sessionID, cfg.websiteID())
	if err != nil {
		p.API.LogWarn("Asyntai request failed", "error", err.Error())
		return &model.CommandResponse{
			ResponseType: model.CommandResponseTypeEphemeral,
			Text:         "Asyntai could not answer that: " + err.Error(),
		}, nil
	}

	// Mattermost keeps a slash command private, so the channel would only ever
	// see a bot post with no question attached. Neither built in response type
	// helps: the default is invisible, and in_channel posts the answer under
	// the asking person's name, which reads as if they answered themselves.
	// So the question is posted as the person and the answer as the bot.
	p.postAsUser(args.UserId, args.ChannelId, args.RootId, question)
	p.postAsBot(args.ChannelId, args.RootId, answer)

	return &model.CommandResponse{}, nil
}

// MessageHasBeenPosted answers a direct message sent to the bot.
func (p *Plugin) MessageHasBeenPosted(_ *plugin.Context, post *model.Post) {
	cfg := p.getConfiguration()

	if !cfg.AllowDirectMessages || strings.TrimSpace(cfg.APIKey) == "" {
		return
	}

	// Never answer ourselves, or any other bot, or a system message, or a
	// question this plugin echoed on somebody's behalf.
	if post.UserId == p.botUserID || post.IsSystemMessage() {
		return
	}
	if post.Props != nil {
		if _, echoed := post.Props[echoProp]; echoed {
			return
		}
	}
	if user, err := p.API.GetUser(post.UserId); err == nil && user.IsBot {
		return
	}

	channel, err := p.API.GetChannel(post.ChannelId)
	if err != nil || channel.Type != model.ChannelTypeDirect {
		return
	}

	// A direct channel is named "<userid>__<userid>". Only answer our own.
	if !strings.Contains(channel.Name, p.botUserID) {
		return
	}

	question := strings.TrimSpace(post.Message)
	if question == "" {
		return
	}

	sessionID := "mm_dm_" + post.UserId

	answer, err2 := p.client().ask(question, sessionID, cfg.websiteID())
	if err2 != nil {
		p.API.LogWarn("Asyntai request failed", "error", err2.Error())
		p.postAsBot(post.ChannelId, post.RootId, "Sorry, I could not answer that: "+err2.Error())
		return
	}

	p.postAsBot(post.ChannelId, post.RootId, answer)
}

// postAsUser echoes the question into the channel under the asker's name.
// The marker prop stops MessageHasBeenPosted answering it a second time when
// the command is used inside a direct message with the bot.
func (p *Plugin) postAsUser(userID, channelID, rootID, message string) {
	if _, err := p.API.CreatePost(&model.Post{
		UserId:    userID,
		ChannelId: channelID,
		RootId:    rootID,
		Message:   message,
		Props:     model.StringInterface{echoProp: true},
	}); err != nil {
		p.API.LogWarn("Could not echo the question", "error", err.Error())
	}
}

func (p *Plugin) postAsBot(channelID, rootID, message string) {
	if _, err := p.API.CreatePost(&model.Post{
		UserId:    p.botUserID,
		ChannelId: channelID,
		RootId:    rootID,
		Message:   message,
	}); err != nil {
		p.API.LogWarn("Could not post the Asyntai answer", "error", err.Error())
	}
}

func main() {
	plugin.ClientMain(&Plugin{})
}
