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
