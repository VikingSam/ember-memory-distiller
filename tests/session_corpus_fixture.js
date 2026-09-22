function fileContentRevision(filePath) {
	try {
		const stat = fs.statSync(filePath, { bigint: true });
		if (!stat.isFile()) return;
		return `file:${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeNs}:${stat.ctimeNs}`;
	} catch {
		return;
	}
}
function sqliteContentRevision(params) {
	try {
		return readTranscriptContentRevisionSync(params);
	} catch {
		return;
	}
}
function isDreamingNarrativeSessionKeyLike(value) {
	return typeof value === "string" && isDreamingNarrativeSessionStoreKey(value);
}
function normalizeComparablePath$1(pathname) {
	const resolved = path.resolve(pathname);
	return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}
function normalizeRealComparablePath(pathname) {
	try {
		return normalizeComparablePath$1(fs.realpathSync(pathname));
	} catch {
		try {
			return normalizeComparablePath$1(path.join(fs.realpathSync(path.dirname(pathname)), path.basename(pathname)));
		} catch {
			return normalizeComparablePath$1(pathname);
		}
	}
}
function rememberArtifactDir(dirs, dir) {
	dirs.set(normalizeRealComparablePath(dir), dir);
}
function classifySessionEntry(sessionKey, entry, cronGeneratedSessionKeys) {
	const generatedByDreamingNarrative = isDreamingNarrativeSessionStoreKey(sessionKey) || isDreamingNarrativeSessionKeyLike(entry.spawnedBy);
	const generatedByCronRun = cronGeneratedSessionKeys.has(sessionKey);
	return {
		generatedByDreamingNarrative,
		generatedByCronRun,
		sessionKind: generatedByCronRun ? "cron" : typeof entry.heartbeatIsolatedBaseSessionKey === "string" && entry.heartbeatIsolatedBaseSessionKey.trim() ? "heartbeat" : generatedByDreamingNarrative || Boolean(entry.spawnedBy) ? "subagent" : sessionKey.includes(":subagent:") ? "subagent" : "interactive"
	};
}
function readParentSessionKeys(entry) {
	const keys = /* @__PURE__ */ new Set();
	for (const value of [entry?.parentSessionKey, entry?.spawnedBy]) {
		if (typeof value !== "string") continue;
		const trimmed = value.trim();
		if (trimmed) keys.add(trimmed);
	}
	return [...keys];
}
function collectCronGeneratedSessionKeys(summaries) {
	const entriesByKey = new Map(summaries.map((summary) => [summary.sessionKey, summary.entry]));
	const cronGeneratedKeys = /* @__PURE__ */ new Set();
	const cache = /* @__PURE__ */ new Map();
	const resolving = /* @__PURE__ */ new Set();
	const isCronGenerated = (sessionKey, entry) => {
		if (isCronRunSessionKey(sessionKey)) {
			cache.set(sessionKey, true);
			cronGeneratedKeys.add(sessionKey);
			return true;
		}
		const cached = cache.get(sessionKey);
		if (cached !== void 0) return cached;
		if (resolving.has(sessionKey)) return false;
		resolving.add(sessionKey);
		const generated = readParentSessionKeys(entry).some((parentKey) => isCronRunSessionKey(parentKey) || isCronGenerated(parentKey, entriesByKey.get(parentKey)));
		resolving.delete(sessionKey);
		cache.set(sessionKey, generated);
		if (generated) cronGeneratedKeys.add(sessionKey);
		return generated;
	};
	for (const summary of summaries) isCronGenerated(summary.sessionKey, summary.entry);
	return cronGeneratedKeys;
}
function toSessionStoreCorpusEntry(agentId, storePath, summary, cronGeneratedSessionKeys) {
	const sessionId = summary.entry.sessionId?.trim();
	if (!sessionId) return null;
	const sessionKey = summary.sessionKey.trim();
	const classification = classifySessionEntry(summary.sessionKey, summary.entry, cronGeneratedSessionKeys);
	const contentRevision = sqliteContentRevision({
		agentId,
		sessionId,
		...sessionKey ? { sessionKey } : {},
		storePath
	});
	return {
		agentId,
		artifactKind: "active-session",
		sessionFile: sessionKey,
		sessionId,
		...contentRevision ? { contentRevision } : {},
		transcriptSource: "sqlite",
		storePath,
		...Number.isFinite(summary.entry.updatedAt) ? { updatedAtMs: summary.entry.updatedAt } : {},
		...sessionKey ? { sessionKey } : {},
		...classification.generatedByDreamingNarrative ? { generatedByDreamingNarrative: true } : {},
		...classification.generatedByCronRun ? { generatedByCronRun: true } : {},
		sessionKind: classification.sessionKind
	};
}
function toRetainedSessionCorpusEntry(agentId, instance, sessionKey, storePath, cronGeneratedSessionKeys) {
	if (!instance.provenanceKnown || instance.acpOwned || instance.entry.pluginOwnerId || instance.entry.hookExternalContentSource) return null;
	const classification = classifySessionEntry(sessionKey, instance.entry, cronGeneratedSessionKeys);
	const contentRevision = sqliteContentRevision({
		agentId,
		sessionId: instance.sessionId,
		...sessionKey ? { sessionKey } : {},
		storePath
	});
	return {
		agentId,
		artifactKind: "retained-session",
		sessionFile: sessionKey,
		sessionId: instance.sessionId,
		...contentRevision ? { contentRevision } : {},
		storePath,
		transcriptSource: "sqlite",
		updatedAtMs: instance.updatedAtMs,
		...sessionKey ? { sessionKey } : {},
		...classification.generatedByDreamingNarrative ? { generatedByDreamingNarrative: true } : {},
		...classification.generatedByCronRun ? { generatedByCronRun: true } : {},
		sessionKind: classification.sessionKind
	};
}
function listSessionTranscriptArtifactFiles(sessionsDir) {
	try {
		return fs.readdirSync(sessionsDir, { withFileTypes: true }).filter((entry) => entry.isFile()).map((entry) => entry.name).filter((name) => isUsageCountedSessionTranscriptFileName(name)).filter((name) => isSessionArchiveArtifactName(name)).map((name) => path.join(sessionsDir, name));
	} catch (err) {
		if (err.code === "ENOENT") return [];
		throw err;
	}
}
function toArtifactCorpusEntry(agentId, artifactPath, sessionId, primaryEntry) {
	const contentRevision = fileContentRevision(artifactPath);
	return {
		agentId,
		artifactKind: "archive-artifact",
		sessionFile: artifactPath,
		sessionId,
		...contentRevision ? { contentRevision } : {},
		...primaryEntry?.generatedByDreamingNarrative ? { generatedByDreamingNarrative: true } : {},
		...primaryEntry?.generatedByCronRun ? { generatedByCronRun: true } : {},
		sessionKind: primaryEntry?.sessionKind ?? "unknown"
	};
}
function listSessionTranscriptCorpusEntriesForAgentSync(agentId, options = {}) {
	const normalizedAgentId = normalizeAgentId(agentId);
	const cfg = getRuntimeConfig();
	const configuredStore = cfg.session?.store;
	const storePath = resolveStorePath(configuredStore, { agentId: normalizedAgentId });
	const sessionsDir = path.dirname(storePath);
	const fixedStoreOwnerAgentId = extractAgentIdFromSessionsDir(sessionsDir);
	const isAgentOwnedFixedStore = fixedStoreOwnerAgentId !== null && normalizeAgentId(fixedStoreOwnerAgentId) === normalizedAgentId;
	const isSharedFixedStore = typeof configuredStore === "string" && configuredStore.trim().length > 0 && !configuredStore.includes("{agentId}") && !isAgentOwnedFixedStore;
	const activeEntriesBySessionId = /* @__PURE__ */ new Map();
	const entryOwnersBySessionId = /* @__PURE__ */ new Map();
	const artifactDirsByPath = /* @__PURE__ */ new Map();
	rememberArtifactDir(artifactDirsByPath, sessionsDir);
	rememberArtifactDir(artifactDirsByPath, resolveSessionTranscriptsDirForAgent(normalizedAgentId));
	const sessionEntries = listSessionEntries({
		agentId: normalizedAgentId,
		hydrateSkillPromptRefs: false,
		storePath
	});
	const retainedInstances = options.includeRetainedSqlite ? listSessionTranscriptInstances({
		agentId: normalizedAgentId,
		hydrateSkillPromptRefs: false,
		readConsistency: "latest",
		storePath
	}) : [];
	const cronGeneratedSessionKeys = collectCronGeneratedSessionKeys([...retainedInstances.map(({ entry, sessionKey }) => ({
		entry,
		sessionKey
	})), ...sessionEntries]);
	for (const summary of sessionEntries) {
		const ownerAgentId = resolveSessionAgentId({
			config: cfg,
			sessionKey: isSharedFixedStore ? summary.sessionKey : canonicalizeMainSessionAlias({
				cfg,
				agentId: normalizedAgentId,
				sessionKey: summary.sessionKey
			}),
			...isSharedFixedStore ? {} : { fallbackAgentId: normalizedAgentId }
		});
		const entry = toSessionStoreCorpusEntry(ownerAgentId, storePath, summary, cronGeneratedSessionKeys);
		if (!entry) continue;
		entryOwnersBySessionId.set(entry.sessionId, ownerAgentId);
		if (ownerAgentId === normalizedAgentId) activeEntriesBySessionId.set(entry.sessionId, entry);
	}
	const includeUnownedArtifacts = !isSharedFixedStore;
	const corpusEntries = [...activeEntriesBySessionId.values()];
	if (options.includeRetainedSqlite) for (const instance of retainedInstances) {
		if (activeEntriesBySessionId.has(instance.sessionId)) continue;
		const sessionKey = isSharedFixedStore ? instance.sessionKey : canonicalizeMainSessionAlias({
			cfg,
			agentId: normalizedAgentId,
			sessionKey: instance.sessionKey
		});
		const ownerAgentId = resolveSessionAgentId({
			config: cfg,
			sessionKey,
			...isSharedFixedStore ? {} : { fallbackAgentId: normalizedAgentId }
		});
		if (ownerAgentId !== normalizedAgentId) continue;
		const entry = toRetainedSessionCorpusEntry(ownerAgentId, instance, sessionKey, storePath, cronGeneratedSessionKeys);
		if (entry?.transcriptSource === "sqlite") corpusEntries.push(entry);
	}
	const scannedArtifactPaths = /* @__PURE__ */ new Set();
	for (const artifactDir of artifactDirsByPath.values()) for (const artifactPath of listSessionTranscriptArtifactFiles(artifactDir)) {
		const normalizedArtifactPath = normalizeRealComparablePath(artifactPath);
		if (scannedArtifactPaths.has(normalizedArtifactPath)) continue;
		scannedArtifactPaths.add(normalizedArtifactPath);
		const primarySessionId = parseUsageCountedSessionIdFromFileName(path.basename(artifactPath));
		if (!primarySessionId) continue;
		const primaryEntry = activeEntriesBySessionId.get(primarySessionId);
		const primaryOwner = entryOwnersBySessionId.get(primarySessionId);
		if (primaryOwner && primaryOwner !== normalizedAgentId) continue;
		if (!primaryOwner && !includeUnownedArtifacts) continue;
		corpusEntries.push(toArtifactCorpusEntry(normalizedAgentId, artifactPath, primarySessionId, primaryEntry));
	}
	return corpusEntries;
}
