.PHONY: bootstrap infra migrate seed dev test e2e generate-data train evaluate reset

bootstrap:
	pnpm bootstrap
infra:
	pnpm infra
migrate:
	pnpm migrate
seed:
	pnpm seed
dev:
	pnpm dev
test:
	pnpm test
e2e:
	pnpm e2e
generate-data:
	pnpm generate:data
train:
	pnpm train
evaluate:
	pnpm evaluate
reset:
	pnpm reset

