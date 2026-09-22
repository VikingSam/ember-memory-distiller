// Extracted from public openclaw 2026.8.1; original functions for regression tests.
async function runMemorySearchMaintenance(params) {
	const dirtyGeneration = params.takeDirtyGeneration();
	let manager;
	try {
		manager = await params.acquireManager();
	} catch (err) {
		params.restoreDirtyGeneration(dirtyGeneration);
		throw toErrorObject(err, "Memory search maintenance manager acquisition failed");
	}
	if (!manager) {
		params.restoreDirtyGeneration(dirtyGeneration);
		return;
	}
	let maintenanceError;
	let incompleteReason;
	try {
		await manager.sync({
			reason: params.reason,
			force: true
		});
		const status = manager.status();
		if (status.dirty === true) {
			params.restoreDirtyGeneration(dirtyGeneration);
			incompleteReason = status.lastSyncError;
		}
	} catch (err) {
		params.restoreDirtyGeneration(dirtyGeneration);
		maintenanceError = toErrorObject(err, "Memory search maintenance failed");
	}
	try {
		await manager.close();
	} catch (err) {
		maintenanceError ??= toErrorObject(err, "Memory search maintenance close failed");
	}
	if (maintenanceError) throw maintenanceError;
	return incompleteReason;
}

class FixtureManager {
	async runSyncPass(params) {
		this.assertFtsOnlySyncAllowed();
		const syncProvider = this.syncProviderGeneration ? this.syncProviderGeneration.provider : this.provider;
		const progress = params?.progress ? this.createSyncProgress(params.progress) : void 0;
		if (progress) progress.report({
			completed: progress.completed,
			total: progress.total,
			label: "Loading vector extension…"
		});
		const vectorReady = syncProvider ? await this.ensureVectorReady() : false;
		const meta = this.readMeta();
		const targetSessionSync = this.hasRequestedTargetSessionSync(params) ? await this.resolveTargetSessionSyncPlan({
			sessions: params?.sessions,
			archiveFiles: params?.archiveFiles
		}) : null;
		const targetArchiveFiles = targetSessionSync?.targetArchiveFiles ?? null;
		const hasTargetArchiveFiles = targetArchiveFiles !== null;
		if (this.hasRequestedTargetSessionSync(params) && !hasTargetArchiveFiles) return;
		if (params?.reason === "cli" && !params.force && !hasTargetArchiveFiles) await this.markSessionStartupCatchupDirtyFiles();
		const syncProviderKey = this.syncProviderGeneration ? this.syncProviderGeneration.providerKey : this.providerKey;
		const syncProviderIdentities = this.syncProviderGeneration?.identities ?? this.resolveProviderIndexIdentities();
		const indexIdentity = resolveMemoryIndexIdentityState({
			meta,
			provider: syncProvider ? {
				id: syncProvider.id,
				model: syncProvider.model
			} : null,
			providerKey: syncProviderKey ?? void 0,
			providerAliases: syncProviderIdentities.slice(1),
			configuredSources: resolveConfiguredSourcesForMeta(this.sources),
			configuredScopeHash: resolveConfiguredScopeHash({
				workspaceDir: this.workspaceDir,
				extraPaths: this.settings.extraPaths,
				multimodal: {
					enabled: this.settings.multimodal.enabled,
					modalities: this.settings.multimodal.modalities,
					maxFileBytes: this.settings.multimodal.maxFileBytes
				}
			}),
			chunkTokens: this.settings.chunking.tokens,
			chunkOverlap: this.settings.chunking.overlap,
			vectorReady,
			hasIndexedChunks: this.hasIndexedChunks(),
			ftsTokenizer: this.settings.store.fts.tokenizer
		});
		const hasIndexedChunks = this.hasIndexedChunks();
		const needsInitialIndex = indexIdentity.status !== "valid" && !hasIndexedChunks;
		const hasOnlyFtsChunks = indexIdentity.status === "missing" && hasIndexedChunks && syncProvider === null && Boolean(this.settings.provider) && this.settings.provider !== "none" && !this.hasSemanticChunks();
		const canRebuildMissingIdentity = syncProvider !== null || !this.settings.provider || this.settings.provider === "none" || hasOnlyFtsChunks;
		const needsMissingIdentityReindex = indexIdentity.status === "missing" && !hasTargetArchiveFiles && canRebuildMissingIdentity;
		const needsExplicitIdentityReindex = params?.reason === "cli" && indexIdentity.status !== "valid" && !hasTargetArchiveFiles;
		const needsChunkingVersionReindex = meta !== null && meta.chunkingVersion !== 3 && !hasTargetArchiveFiles;
		const canRunRetryFullReindex = indexIdentity.status !== "missing" || needsInitialIndex || canRebuildMissingIdentity;
		const needsFullReindex = params?.force && !hasTargetArchiveFiles || needsInitialIndex || needsMissingIdentityReindex || needsExplicitIdentityReindex || needsChunkingVersionReindex || this.memoryFullRetryDirty && canRunRetryFullReindex || this.sessionsFullRetryDirty && indexIdentity.status !== "valid" && canRunRetryFullReindex;
		const needsFullSessionReindex = needsFullReindex || this.sessionsFullRetryDirty;
		if (indexIdentity.status !== "valid" && !needsFullReindex) {
			this.dirty = true;
			if (markMemoryTargetArchiveFilesDirty({
				sessionsDirtyFiles: this.sessionsDirtyFiles,
				targetArchiveFiles
			})) this.sessionsDirty = true;
			return;
		}
		if (!needsFullSessionReindex) {
			const targetedSessionSync = await runMemoryTargetedSessionSync({
				hasSessionSource: this.sources.has("sessions"),
				targetArchiveFiles,
				reason: params?.reason,
				progress: progress ?? void 0,
				sessionsFullRetryDirty: this.sessionsFullRetryDirty,
				sessionsReconcileDirty: this.sessionsReconcileDirty,
				sessionsDirtyFiles: this.sessionsDirtyFiles,
				syncArchiveFiles: async (targetedParams) => {
					await this.syncArchiveFiles({
						...targetedParams,
						corpusEntries: targetSessionSync?.corpusEntries
					});
				},
				shouldFallbackOnError: (err) => this.shouldFallbackOnError(err),
				activateFallbackProvider: async (reason) => {
					this.endSyncProviderGeneration();
					return await this.activateFallbackProvider(reason);
				}
			});
			if (targetedSessionSync.handled) {
				this.sessionsDirty = targetedSessionSync.sessionsDirty;
				if (targetedSessionSync.failure) this.syncOutcomes.recordActiveFailure(targetedSessionSync.failure.error);
				return;
			}
		}
		try {
			if (needsFullReindex) {
				await this.runInPlaceReindex({
					reason: params?.reason,
					force: params?.force,
					progress: progress ?? void 0
				});
				return;
			}
			const shouldSyncMemory = this.sources.has("memory") && (!hasTargetArchiveFiles && params?.force || needsFullReindex || this.dirty);
			const shouldSyncSessions = this.shouldSyncSessions(params, needsFullReindex);
			if (this.shouldDeferSourceWideBatch()) {
				await this.executeSourceWideSync({
					shouldSyncMemory,
					shouldSyncSessions,
					needsFullReindex,
					needsFullSessionReindex,
					targetArchiveFiles: targetArchiveFiles ? Array.from(targetArchiveFiles) : void 0,
					progress: progress ?? void 0
				});
				if (shouldSyncMemory) this.clearMemoryRetryState();
				if (shouldSyncSessions) this.clearSessionRetryState();
				else this.refreshSessionDirtyFlag();
			} else {
				if (shouldSyncMemory) {
					await this.syncMemoryFiles({
						needsFullReindex,
						progress: progress ?? void 0
					});
					this.clearMemoryRetryState();
				}
				if (shouldSyncSessions) {
					await this.syncArchiveFiles({
						needsFullReindex: needsFullSessionReindex,
						targetArchiveFiles: targetArchiveFiles ? Array.from(targetArchiveFiles) : void 0,
						progress: progress ?? void 0
					});
					this.clearSessionRetryState();
				} else this.refreshSessionDirtyFlag();
			}
		} catch (err) {
			const reason = formatErrorMessage(err);
			const shouldFallback = this.shouldFallbackOnError(err);
			if (shouldFallback) this.endSyncProviderGeneration();
			if (shouldFallback && await this.activateFallbackProvider(reason)) {
				if (needsFullReindex && !hasTargetArchiveFiles) {
					this.beginSyncProviderGeneration();
					await this.runInPlaceReindex({
						reason: params?.reason ?? "fallback",
						force: true,
						progress: progress ?? void 0
					});
				}
				return;
			}
			if (!this.provider && this.fts.enabled && this.shouldFallbackOnError(err)) {
				this.syncOutcomes.recordActiveFailure(err);
				log$6.warn(`memory embeddings unavailable; leaving memory index dirty: ${reason}`);
				return;
			}
			throw err;
		}
	}
	restoreReindexRetryState(snapshot) {
		this.dirty = snapshot.dirty || this.dirty;
		this.memoryFullRetryDirty = snapshot.memoryFullRetryDirty || this.memoryFullRetryDirty;
		this.sessionsFullRetryDirty = snapshot.sessionsFullRetryDirty || this.sessionsFullRetryDirty;
		this.sessionsReconcileDirty = snapshot.sessionsReconcileDirty || this.sessionsReconcileDirty;
		this.sessionsDirtyFiles = /* @__PURE__ */ new Set([...snapshot.sessionsDirtyFiles, ...this.sessionsDirtyFiles]);
		this.sessionsDirty = snapshot.sessionsDirty || this.sessionsDirty || this.sessionsFullRetryDirty || this.sessionsReconcileDirty || this.sessionsDirtyFiles.size > 0;
	}
}
