// Command octofinance runs the Go backend of OctoFinance.
//
// It serves the same HTTP API and frontend as the Python backend and uses the
// same data/ directory, so either backend can be started against one install.
package main

import (
	"flag"
	"fmt"
	"log"
	"net"
	"os"

	"github.com/satomic/octofinance/backend-go/internal/app"
)

func main() {
	host := flag.String("host", envOr("HOST", "0.0.0.0"), "listen address")
	port := flag.String("port", envOr("PORT", "8000"), "listen port")
	version := flag.Bool("version", false, "print the version and exit")
	tool := flag.String("tool", "", "invoke one AI tool and print its result (debugging/tests)")
	toolArgs := flag.String("args", "{}", "JSON arguments for -tool")
	listTools := flag.Bool("list-tools", false, "print the registered AI tool names and exit")
	flag.Parse()
	if *listTools {
		for _, n := range app.ToolNames() {
			fmt.Println(n)
		}
		return
	}
	if *tool != "" {
		out, err := app.RunTool(*tool, *toolArgs)
		if err != nil {
			log.Fatal(err)
		}
		fmt.Println(out)
		return
	}
	if *version {
		fmt.Printf("OctoFinance %s (Go backend)\n", app.AppVersion)
		return
	}
	if err := app.Run(net.JoinHostPort(*host, *port)); err != nil {
		log.Fatal(err)
	}
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
