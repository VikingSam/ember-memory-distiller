// Extracted search method from OpenClaw 2026.8.1 plus V4; see OPENCLAW-LICENSE.txt.
class SearchFixture {
	async searchCandidates(normalizedQuery, opts) {
		let releaseGeneration;
		return await this.withManagerOperation(async () => {
			opts?.onDebug?.({ backend: "builtin" });
			if (this.providerRequirement.mode === "required") {
				await this.ensureProviderInitialized();
				this.assertRequiredProviderAvailable("search");
			}
			let hasIndexedContent = this.hasIndexedContent();
			if (!hasIndexedContent) {
				try {
					await this.syncAdmitted({
						reason: "search",
						force: true
					}, { allowEmbeddingBootstrapFallback: true });
				} catch (err) {
					if (this.providerRequirement.mode === "optional" && this.shouldFallbackOnError(err)) {
						const failedProvider = this.provider?.id ?? this.settings.provider;
						await this.retireCurrentProvider().catch((retireErr) => {
							const message = redactSensitiveText(formatErrorMessage(retireErr), { mode: "tools" });
							log$1.warn(`memory search-bootstrap: failed to retire embedding provider: ${message}`);
						});
						this.markEmbeddingBootstrapFailure(err, { provider: failedProvider });
						await this.syncAdmitted({
							reason: "search",
							force: true
						}).catch((fallbackErr) => {
							const message = redactSensitiveText(formatErrorMessage(fallbackErr), { mode: "tools" });
							log$1.warn(`memory sync failed (search-bootstrap-fallback): ${message}`);
						});
					} else log$1.warn(`memory sync failed (search-bootstrap): ${String(err)}`);
				}
				hasIndexedContent = this.hasIndexedContent();
			}
			const preflight = resolveMemorySearchPreflight({
				query: normalizedQuery,
				hasIndexedContent
			});
			if (!preflight.shouldSearch) {
				if (this.embeddingBootstrapFailure) opts?.onDebug?.({
					backend: "builtin",
					embeddingBootstrap: this.embeddingBootstrapFailure
				});
				return [];
			}
			const cleaned = preflight.normalizedQuery;
			const embeddingBootstrapKeywordOnly = await this.ensureEmbeddingProviderForSearch(opts?.onDebug);
			const sessionStartSync = this.claimSessionWarmSync(opts?.sessionKey);
			if (!embeddingBootstrapKeywordOnly && preflight.shouldInitializeProvider && !this.provider && (this.providerLifecycle.mode === "pending" || this.providerLifecycle.mode === "degraded" && this.providerLifecycle.providerId !== this.settings.provider)) {
				this.resetProviderInitializationForRetry();
				await this.ensureProviderInitialized();
			}
			this.assertRequiredProviderAvailable("search");
			if (!embeddingBootstrapKeywordOnly && !this.provider && this.providerLifecycle.mode === "degraded") {
				if (await this.activateFallbackProvider(this.providerLifecycle.reason).catch((fallbackErr) => {
					log$1.warn(`memory search: failed to activate fallback provider: ${formatErrorMessage(fallbackErr)}`);
					return false;
				})) this.refreshIndexIdentityDirty({ providerKeyKnown: this.providerInitialized });
			}
			const indexIdentity = embeddingBootstrapKeywordOnly ? this.refreshKeywordFallbackIndexIdentity() : this.refreshIndexIdentityDirty({ providerKeyKnown: this.providerInitialized });
			if (indexIdentity.status === "missing" && hasIndexedContent) await this.syncAdmitted({
				reason: "search",
				force: true
			}, { allowEmbeddingBootstrapFallback: true }).catch((err) => {
				log$1.warn(`memory sync failed (search-identity-repair): ${formatErrorMessage(err)}`);
			});
			let repairedIndexIdentity = indexIdentity.status === "missing" && hasIndexedContent ? embeddingBootstrapKeywordOnly ? this.refreshKeywordFallbackIndexIdentity() : this.refreshIndexIdentityDirty({ providerKeyKnown: this.providerInitialized }) : indexIdentity;
			if (repairedIndexIdentity.status === "mismatched" && !embeddingBootstrapKeywordOnly && await this.adoptPublishedFallbackProviderIfMatched()) repairedIndexIdentity = this.refreshIndexIdentityDirty({ providerKeyKnown: this.providerInitialized });
			if (repairedIndexIdentity.status !== "valid") return [];
			const backgroundSearchSync = startAsyncSearchSync({
				enabled: (this.settings.sync.onSearch || sessionStartSync) && (this.purpose === "default" || this.purpose === "cli"),
				dirty: this.dirty,
				sessionsDirty: this.sessionsDirty,
				sync: async (params) => await this.syncPublishedIndexInBackground(params),
				onError: (err) => {
					log$1.warn(`memory sync failed (search): ${String(err)}`);
				}
			});
			if (backgroundSearchSync) {
				const trackedSearchSync = backgroundSearchSync.finally(() => {
					this.activeBackgroundSearchSyncs.delete(trackedSearchSync);
				});
				this.activeBackgroundSearchSyncs.add(trackedSearchSync);
			}
			for (let identityAttempt = 0; identityAttempt < 2; identityAttempt += 1) {
				releaseGeneration = await acquireMemoryIndexReadGeneration(this.settings.store.databasePath, opts?.signal);
				if (embeddingBootstrapKeywordOnly) break;
				const leasedIdentity = this.refreshIndexIdentityDirty({ providerKeyKnown: this.providerInitialized });
				if (leasedIdentity.status === "valid") break;
				releaseGeneration();
				releaseGeneration = void 0;
				if (identityAttempt > 0 || leasedIdentity.status !== "mismatched" || !await this.adoptPublishedFallbackProviderIfMatched()) return [];
			}
			const minScore = opts?.minScore ?? this.settings.query.minScore;
			const maxResults = opts?.maxResults ?? this.settings.query.maxResults;
			const searchSources = opts?.sources && opts.sources.length > 0 ? uniqueValues(opts.sources).filter((s) => this.sources.has(s)) : void 0;
			if (opts?.sources && opts.sources.length > 0 && (!searchSources || searchSources.length === 0)) return [];
			const sourceFilterList = searchSources ?? this.settings.searchSources;
			const hybrid = this.settings.query.hybrid;
			const candidates = Math.min(200, Math.max(1, Math.floor(maxResults * hybrid.candidateMultiplier)));
			if (embeddingBootstrapKeywordOnly || !this.provider) {
				this.assertRequiredProviderAvailable("search");
				if (!this.fts.enabled || !this.fts.available) {
					log$1.warn("memory search: no provider and FTS unavailable");
					return [];
				}
				const keywordResults = await this.searchKeywordWithFallback(cleaned, candidates, { boostFallbackRanking: true }, sourceFilterList).catch((err) => {
					log$1.warn(`memory search: FTS keyword query failed: ${formatErrorMessage(err)}`);
					return [];
				});
				return await this.finalizeKeywordOnlyResults({
					results: keywordResults,
					temporalDecay: hybrid.temporalDecay,
					maxResults,
					minScore,
					activeProjectKeys: opts?.activeProjectKeys
				});
			}
			let semanticProvider = this.provider;
			let semanticProviderRuntime = this.providerRuntime;
			let vectorProviderIdentity = {
				model: semanticProvider.model,
				aliases: this.resolveProviderIndexIdentities().slice(1).map((identity) => identity.model)
			};
			const loadKeywordResults = async () => hybrid.enabled && this.fts.enabled && this.fts.available ? await this.searchKeywordWithFallback(cleaned, candidates, { boostFallbackRanking: true }, sourceFilterList).catch((err) => {
				log$1.warn(`memory search: FTS hybrid keyword query failed: ${formatErrorMessage(err)}`);
				return [];
			}) : [];
			let keywordResults = [];
			let queryVec;
			const releaseSemanticProvider = this.acquireProviderUse(semanticProvider);
			try {
				keywordResults = await loadKeywordResults();
				if (opts?.lexicalOnly) return await this.finalizeKeywordOnlyResults({
					results: keywordResults,
					temporalDecay: hybrid.temporalDecay,
					maxResults,
					minScore,
					activeProjectKeys: opts?.activeProjectKeys
				});
				try {
					queryVec = await this.embedQueryWithRetry(cleaned, opts?.signal, semanticProvider, false, semanticProviderRuntime);
				} catch (err) {
					releaseSemanticProvider();
					if (opts?.signal?.aborted) throw err;
					this.markLocalEmbeddingProviderDegraded(err);
					const message = formatErrorMessage(err);
					if (this.shouldFallbackOnError(err) ? await this.activateFallbackProvider(message).catch((fallbackErr) => {
						log$1.warn(`memory search: failed to activate fallback provider: ${formatErrorMessage(fallbackErr)}`);
						return false;
					}) : false) {
						if (this.refreshIndexIdentityDirty({ providerKeyKnown: this.providerInitialized }).status !== "valid") return [];
						if (!this.provider) return [];
						semanticProvider = this.provider;
						semanticProviderRuntime = this.providerRuntime;
						vectorProviderIdentity = {
							model: semanticProvider.model,
							aliases: this.resolveProviderIndexIdentities().slice(1).map((identity) => identity.model)
						};
						const releaseFallbackProvider = this.acquireProviderUse(semanticProvider);
						try {
							keywordResults = await loadKeywordResults();
							queryVec = await this.embedQueryWithRetry(cleaned, opts?.signal, semanticProvider, false, semanticProviderRuntime);
						} catch (fallbackErr) {
							releaseFallbackProvider();
							if (!opts?.signal?.aborted) this.markLocalEmbeddingProviderDegraded(fallbackErr);
							throw fallbackErr;
						} finally {
							releaseFallbackProvider();
						}
					} else if (!this.provider && this.fts.enabled && this.fts.available) {
						this.assertRequiredProviderAvailable("search");
						log$1.warn(`memory search: embeddings unavailable; using keyword-only results: ${message}`);
						return await this.finalizeKeywordOnlyResults({
							results: keywordResults,
							temporalDecay: hybrid.temporalDecay,
							maxResults,
							minScore,
							activeProjectKeys: opts?.activeProjectKeys
						});
					} else throw err;
				}
			} finally {
				releaseSemanticProvider();
			}
			const vectorResults = queryVec.some((v) => v !== 0) ? await this.searchVector(queryVec, candidates, sourceFilterList, vectorProviderIdentity, opts?.signal).catch((err) => {
				opts?.signal?.throwIfAborted();
				log$1.warn(`memory search: vector query failed: ${formatErrorMessage(err)}`);
				return [];
			}) : [];
			if (!hybrid.enabled || !this.fts.enabled || !this.fts.available) return applyProjectRanking(applyImportanceMultiplier(await applyTemporalDecayToHybridResults({
				results: vectorResults,
				temporalDecay: hybrid.temporalDecay,
				workspaceDir: this.workspaceDir
			})), opts?.activeProjectKeys).filter((entry) => entry.score >= minScore).slice(0, maxResults);
			return selectHybridSearchResults({
				merged: await this.mergeHybridResults({
					query: cleaned,
					vector: vectorResults,
					keyword: keywordResults,
					vectorWeight: hybrid.vectorWeight,
					textWeight: hybrid.textWeight,
					mmr: hybrid.mmr,
					temporalDecay: hybrid.temporalDecay,
					activeProjectKeys: opts?.activeProjectKeys
				}),
				keyword: keywordResults,
				maxResults,
				minScore
			});
		}).finally(() => {
			releaseGeneration?.();
		});
	}
}
