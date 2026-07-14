package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"autotoken-pplink/internal/config"
	"autotoken-pplink/internal/paypal"
	"autotoken-pplink/internal/proxyutil"
)

type options struct {
	configPath        string
	entity            string
	maxRetry          int
	mode              string
	proxy             string
	retryWait         int
	stopAtPMRedirects bool
	token             string
	usProxy           string
}

type payPalSession interface {
	SetStopAtPMRedirects(bool)
	SetProcessorEntity(string)
	ExtractPayPalLink() (*paypal.PayPalLink, error)
}

type appDeps struct {
	loadConfig func(string) (*config.Config, error)
	parseToken func(string) (paypal.GPTToken, error)
	newSession func(
		paypal.GPTToken,
		string,
		string,
		string,
		func(string, ...any),
	) (payPalSession, error)
	rotateSID func(string) string
	sleep     func(time.Duration)
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdin, os.Stderr, productionDeps()))
}

func productionDeps() appDeps {
	return appDeps{
		loadConfig: config.Load,
		parseToken: paypal.ParseGPTToken,
		newSession: func(
			token paypal.GPTToken,
			mode string,
			jpProxy string,
			usProxy string,
			logf func(string, ...any),
		) (payPalSession, error) {
			return paypal.NewStripeSession(token, mode, jpProxy, usProxy, logf)
		},
		rotateSID: paypal.RotateSID,
		sleep:     time.Sleep,
	}
}

func newFlagSet(output io.Writer) (*flag.FlagSet, *options) {
	opts := &options{}
	flags := flag.NewFlagSet(os.Args[0], flag.ContinueOnError)
	flags.SetOutput(output)
	flags.StringVar(&opts.configPath, "config", "config.json", "配置文件")
	flags.StringVar(&opts.entity, "entity", "", "processor_entity (空 = 跟随 mode 默认: us→openai_llc, eu/br→openai_ie)")
	flags.IntVar(&opts.maxRetry, "max-retry", 0, "失败时最大重试次数,0 = 无限重试")
	flags.StringVar(&opts.mode, "mode", "us", "checkout 模式: us(US/USD/hosted) | eu(FR/EUR/custom,JP 单代理) | br(BR/BRL/custom,JP 单代理)")
	flags.StringVar(&opts.proxy, "proxy", "", "JP 代理(checkout + approve)")
	flags.IntVar(&opts.retryWait, "retry-wait", 0, "重试前等待秒数")
	flags.BoolVar(&opts.stopAtPMRedirects, "stop-at-pm-redirects", false, "拿到 pm-redirects.stripe.com URL 就停,不再 follow 到 paypal.com")
	flags.StringVar(&opts.token, "token", "", "直接传token(不走stdin)")
	flags.StringVar(&opts.usProxy, "us-proxy", "", "US 代理(PM/confirm/poll); EU/BR 模式留空只走 JP")
	return flags, opts
}

func run(args []string, stdin io.Reader, stderr io.Writer, deps appDeps) int {
	flags, opts := newFlagSet(stderr)
	if err := flags.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}

	cfg := &config.Config{}
	if loaded, err := deps.loadConfig(opts.configPath); err == nil && loaded != nil {
		cfg = loaded
	}
	jpProxy := strings.TrimSpace(cfg.ProxyJP)
	usProxy := strings.TrimSpace(cfg.ProxyUS)
	if override := strings.TrimSpace(opts.proxy); override != "" {
		jpProxy = override
	}
	if override := strings.TrimSpace(opts.usProxy); override != "" {
		usProxy = override
	}

	settings := paypal.CheckoutSettingsForMode(opts.mode)
	mode := settings.Mode
	if mode != "us" && usProxy != "" {
		fmt.Fprintf(
			stderr,
			"[pplink] %s 模式忽略 us-proxy(%s),所有请求走 JP\n",
			strings.ToUpper(mode),
			maskProxy(usProxy),
		)
		usProxy = ""
	}

	token := strings.TrimSpace(opts.token)
	if token == "" && flags.NArg() > 0 {
		token = strings.TrimSpace(flags.Arg(0))
	}
	if token == "-" {
		token = scanLine(stdin)
	}
	if token == "" {
		fmt.Fprint(stderr, "请粘贴 ChatGPT Token: ")
		token = scanLine(stdin)
	}
	if token == "" {
		fmt.Fprintln(stderr, "token 为空")
		return 1
	}

	for attempt := 1; ; attempt++ {
		attemptJP := jpProxy
		attemptUS := usProxy
		if attempt > 1 {
			if jpProxy != "" {
				attemptJP = deps.rotateSID(jpProxy)
			}
			if usProxy != "" {
				attemptUS = deps.rotateSID(usProxy)
			}
		}

		fmt.Fprintf(stderr, "\n══════════════ pplink #%d ══════════════\n", attempt)
		fmt.Fprintf(stderr, "[pplink] JP proxy: %s\n", maskProxy(attemptJP))
		fmt.Fprintf(stderr, "[pplink] US proxy: %s\n", maskProxy(attemptUS))

		gptToken, err := deps.parseToken(token)
		if err != nil {
			fmt.Fprintf(stderr, "[pplink] #%d ❌ token: %v\n", attempt, err)
			return 1
		}
		logf := func(format string, values ...any) {
			fmt.Fprintf(stderr, "[pplink] "+format+"\n", values...)
		}
		session, err := deps.newSession(gptToken, mode, attemptJP, attemptUS, logf)
		if err == nil {
			session.SetStopAtPMRedirects(opts.stopAtPMRedirects)
			session.SetProcessorEntity(opts.entity)
			var link *paypal.PayPalLink
			link, err = session.ExtractPayPalLink()
			if err == nil && link != nil && strings.TrimSpace(link.FullURL) != "" {
				fmt.Fprintln(stderr)
				fmt.Fprintln(stderr, "═══════════════════════════════════════════")
				fmt.Fprintf(stderr, "Authorize URL: %s\n", strings.TrimSpace(link.FullURL))
				fmt.Fprintln(stderr, "═══════════════════════════════════════════")
				return 0
			}
		} else {
			err = fmt.Errorf("创建 session 失败: %s", proxyutil.RedactText(err.Error(), attemptJP, attemptUS))
		}
		if err == nil {
			err = fmt.Errorf("未提取到 PayPal URL")
		}
		fmt.Fprintf(stderr, "[pplink] #%d ❌ %s\n", attempt, proxyutil.RedactText(err.Error(), attemptJP, attemptUS))

		if opts.maxRetry > 0 && attempt >= opts.maxRetry {
			fmt.Fprintf(stderr, "[pplink] 达到最大重试次数 %d,放弃\n", opts.maxRetry)
			return 1
		}
		if opts.retryWait > 0 {
			deps.sleep(time.Duration(opts.retryWait) * time.Second)
		}
	}
}

func scanLine(input io.Reader) string {
	scanner := bufio.NewScanner(input)
	if scanner.Scan() {
		return strings.TrimSpace(scanner.Text())
	}
	return ""
}

func maskProxy(proxy string) string {
	return proxyutil.Mask(proxy)
}
