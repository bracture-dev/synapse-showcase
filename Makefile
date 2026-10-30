.PHONY: build run run-http typecheck lint test verify sync clean

# Build: compile the server and copy its skill into build/
build:
	npm run build

# Run server in stdio mode
run: build
	node build/index.js --stdio --data-file workspace/showcase/progress.json

# Run server in HTTP mode on 127.0.0.1
run-http: build
	node build/index.js --http --port 27249 --data-file workspace/showcase/progress.json

# Verify
typecheck:
	npm run typecheck

lint:
	npm run lint

test:
	npm test

verify: typecheck lint test

# Copy the manifest version into package.json, its lock and src/constants.ts
sync:
	node scripts/sync.mjs

clean:
	rm -rf build
