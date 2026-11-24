from fastapi import APIRouter

from app.api.v1 import (
    admin, auth, builder, chat, contracts, deploys, documents, downloads, evidence,
    extensions, files, git_ops, github, jobs, memory, local_exec, local_setup,
    remote, repos, resume, settings_instructions, settings_llm,
    settings_memory, settings_quota, status, tasks, thesis,
)

api_router = APIRouter()
api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(builder.router, tags=["builder"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(contracts.router, tags=["contracts"])
api_router.include_router(deploys.router, tags=["deploys"])
api_router.include_router(documents.router, tags=["documents"])
api_router.include_router(downloads.router, tags=["downloads"])
api_router.include_router(evidence.router, tags=["evidence"])
api_router.include_router(extensions.router, tags=["extensions"])
api_router.include_router(files.router, tags=["files"])
api_router.include_router(git_ops.router, tags=["git"])
api_router.include_router(github.router, tags=["github"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(local_exec.router, tags=["local"])
api_router.include_router(local_setup.router, tags=["local"])
api_router.include_router(memory.router, tags=["memory"])
api_router.include_router(remote.router, tags=["remote"])
api_router.include_router(repos.router, tags=["repos"])
api_router.include_router(resume.router, tags=["resume"])
api_router.include_router(settings_instructions.router, tags=["settings"])
api_router.include_router(settings_llm.router, tags=["settings"])
api_router.include_router(settings_memory.router, tags=["settings"])
api_router.include_router(settings_quota.router, tags=["settings"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(thesis.router, tags=["thesis"])
api_router.include_router(status.router, tags=["status"])