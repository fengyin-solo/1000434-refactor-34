.PHONY: install backend frontend check check-backend check-frontend

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

# 本地自检：后端跑能耗口径/填报/复核自检，前端做类型检查与构建，任一失败立即返回非 0。
check: check-backend check-frontend

check-backend:
	cd backend && .venv/bin/python scripts/selfcheck.py

check-frontend:
	cd frontend && npm run build
