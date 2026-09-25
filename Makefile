.PHONY: install backend frontend check check-backend check-frontend

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

# 本地自检：先验证后端依赖与能耗口径/填报复核链路，再构建前端（含 vue-tsc 类型检查）。
check: check-backend check-frontend

check-backend:
	cd backend && if [ -x .venv/bin/python ]; then .venv/bin/python selfcheck.py; else python3 selfcheck.py; fi

check-frontend:
	cd frontend && npm run build
