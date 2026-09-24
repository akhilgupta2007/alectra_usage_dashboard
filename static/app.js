let chart = null;
let globalData = null;
let currentView = 'energy'; // 'energy' or 'cost'

// DOM Elements
const syncStatusEl = document.getElementById('syncStatus');
const btnSync = document.getElementById('btnSync');
const btnSettings = document.getElementById('btnSettings');
const btnCloseSettings = document.getElementById('btnCloseSettings');
const settingsModal = document.getElementById('settingsModal');
const settingsForm = document.getElementById('settingsForm');
const scanIntervalMinutesInput = document.getElementById('scanIntervalMinutes');
const archiveRetentionDaysInput = document.getElementById('archiveRetentionDays');
const timeShiftHoursInput = document.getElementById('timeShiftHours');
const btnReimport = document.getElementById('btnReimport');
const dateRangeSelect = document.getElementById('dateRange');
const resolutionSelect = document.getElementById('resolution');
const customDateGroup = document.getElementById('customDateGroup');
const customStartInput = document.getElementById('customStart');
const customEndInput = document.getElementById('customEnd');
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');

// Scraper Specific DOM Elements
const scraperRunTimeInput = document.getElementById('scraperRunTime');
const scraperConfigStatusEl = document.getElementById('scraperConfigStatus');
const scrapeFromDateInput = document.getElementById('scrapeFromDate');
const scrapeToDateInput = document.getElementById('scrapeToDate');
const btnTriggerManualScrape = document.getElementById('btnTriggerManualScrape');

// History List Elements
const historyList = document.getElementById('historyList');
const historyCountBadge = document.getElementById('historyCountBadge');
const historyTableBody = document.getElementById('historyTableBody');

// Series toggle checkboxes
const chkShowImport = document.getElementById('chkShowImport');
const chkShowExport = document.getElementById('chkShowExport');
let userExplicitlyToggledExport = false;

// View Toggle buttons
const btnViewEnergy = document.getElementById('btnViewEnergy');
const btnViewCost = document.getElementById('btnViewCost');
const chartSubtitle = document.getElementById('chartSubtitle');

// Chart Style state
let currentChartType = 'bar'; // 'bar' or 'area'
let activeScrapePollTimer = null;

const btnStyleBar = document.getElementById('btnStyleBar');
const btnStyleArea = document.getElementById('btnStyleArea');
const rateLegendBar = document.getElementById('rateLegendBar');
const legendUlo = document.getElementById('legendUlo');
const legendTier1 = document.getElementById('legendTier1');
const legendTier2 = document.getElementById('legendTier2');
const legendExport = document.getElementById('legendExport');

// KPI elements
const kpiConsumptionVal = document.getElementById('kpiConsumption');
const kpiConsumptionCost = document.getElementById('kpiConsumptionCost');
const kpiProductionVal = document.getElementById('kpiProduction');
const kpiProductionCost = document.getElementById('kpiProductionCost');
const kpiNetVal = document.getElementById('kpiNet');
const kpiNetCost = document.getElementById('kpiNetCost');
const kpiPeakVal = document.getElementById('kpiPeak');

// Overlay elements
const chartLoading = document.getElementById('chartLoading');
const chartEmpty = document.getElementById('chartEmpty');

// Drill-down elements & state
const drilldownBadge = document.getElementById('drilldownBadge');
const drilldownLabel = document.getElementById('drilldownLabel');
const btnResetDrilldown = document.getElementById('btnResetDrilldown');

let isDrillDownActive = false;
let preDrillDownState = null;
let isDrillDownLoading = false;

// Error Toast & Modal Elements
const errorToast = document.getElementById('errorToast');
const errorToastContent = document.getElementById('errorToastContent');
const errorToastTitle = document.getElementById('errorToastTitle');
const errorToastMsg = document.getElementById('errorToastMsg');
const btnToastDetails = document.getElementById('btnToastDetails');
const btnDismissToast = document.getElementById('btnDismissToast');

const errorModal = document.getElementById('errorModal');
const errorModalTitle = document.getElementById('errorModalTitle');
const errorModalMessage = document.getElementById('errorModalMessage');
const btnCloseErrorModal = document.getElementById('btnCloseErrorModal');
const btnCopyError = document.getElementById('btnCopyError');
const btnCopyErrorText = document.getElementById('btnCopyErrorText');
const btnClearError = document.getElementById('btnClearError');

let activeErrorMessage = '';
let activeErrorTitle = '';
let userDismissedError = false;

function showErrorToast(message, title = "Error Occurred") {
    if (!message) return;
    activeErrorMessage = message;
    activeErrorTitle = title;
    
    if (errorToastTitle) errorToastTitle.textContent = title;
    if (errorToastMsg) errorToastMsg.textContent = message;
    if (errorToast) errorToast.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
}

function hideErrorToast() {
    if (errorToast) errorToast.classList.add('hidden');
}

function openErrorModal() {
    if (!activeErrorMessage) return;
    if (errorModalTitle) errorModalTitle.textContent = activeErrorTitle || "Error Details";
    if (errorModalMessage) errorModalMessage.textContent = activeErrorMessage;
    if (errorModal) errorModal.classList.remove('hidden');
    if (btnCopyErrorText) btnCopyErrorText.textContent = "Copy Error";
    if (window.lucide) lucide.createIcons();
}

function closeErrorModal() {
    if (errorModal) errorModal.classList.add('hidden');
}

async function clearErrorGlobally() {
    hideErrorToast();
    closeErrorModal();
    activeErrorMessage = '';
    userDismissedError = true;
    
    try {
        await fetch('/api/status/clear-error', { method: 'POST' });
        await fetchStatus();
    } catch (e) {
        console.error("Failed to clear error on server:", e);
    }
}

// Attach Error Toast & Modal Event Listeners
if (errorToastContent) {
    errorToastContent.addEventListener('click', openErrorModal);
}
if (btnToastDetails) {
    btnToastDetails.addEventListener('click', (e) => {
        e.stopPropagation();
        openErrorModal();
    });
}
if (btnDismissToast) {
    btnDismissToast.addEventListener('click', (e) => {
        e.stopPropagation();
        clearErrorGlobally();
    });
}
if (btnCloseErrorModal) {
    btnCloseErrorModal.addEventListener('click', closeErrorModal);
}
if (btnClearError) {
    btnClearError.addEventListener('click', clearErrorGlobally);
}
if (btnCopyError) {
    btnCopyError.addEventListener('click', async () => {
        if (!activeErrorMessage) return;
        try {
            await navigator.clipboard.writeText(activeErrorMessage);
            if (btnCopyErrorText) btnCopyErrorText.textContent = "✓ Copied!";
            setTimeout(() => {
                if (btnCopyErrorText) btnCopyErrorText.textContent = "Copy Error";
            }, 2500);
        } catch (err) {
            const textarea = document.createElement('textarea');
            textarea.value = activeErrorMessage;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            if (btnCopyErrorText) btnCopyErrorText.textContent = "✓ Copied!";
            setTimeout(() => {
                if (btnCopyErrorText) btnCopyErrorText.textContent = "Copy Error";
            }, 2500);
        }
    });
}

// Initialize Lucide icons
lucide.createIcons();

// Helper: Format values
function formatVal(val) {
    return val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Helper: Format File Sizes
function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Helper: Format Date/Time for display (using UTC face values for interval times)
function formatDate(timestampMs) {
    const d = new Date(timestampMs);
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const day = days[d.getUTCDay()];
    const yr = d.getUTCFullYear();
    const mo = String(d.getUTCMonth() + 1).padStart(2, '0');
    const da = String(d.getUTCDate()).padStart(2, '0');
    const hr = String(d.getUTCHours()).padStart(2, '0');
    const mi = String(d.getUTCMinutes()).padStart(2, '0');
    return `${day}, ${yr}-${mo}-${da} ${hr}:${mi}`;
}

// Helper: Format Date/Time using local browser timezone for actual processing times
function formatLocalTime(timestampMs) {
    const d = new Date(timestampMs);
    const yr = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, '0');
    const da = String(d.getDate()).padStart(2, '0');
    const hr = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${yr}-${mo}-${da} ${hr}:${mi}`;
}
// Helper: Format a JS timestamp in ms to a short date string like "Jan 01, 2026"
function formatShortDate(tsMs) {
    if (!tsMs) return null;
    const d = new Date(tsMs);
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const mo = months[d.getUTCMonth()];
    const da = String(d.getUTCDate()).padStart(2, '0');
    const yr = d.getUTCFullYear();
    return `${mo} ${da}, ${yr}`;
}

// Helper: Build a compact date range string like "Jan 01 – Jan 30, 2026"
function formatDateRange(fromMs, toMs) {
    if (!fromMs) return null;
    const dFrom = new Date(fromMs);
    const dTo = toMs ? new Date(toMs) : dFrom;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const fromStr = `${months[dFrom.getUTCMonth()]} ${String(dFrom.getUTCDate()).padStart(2,'0')}`;
    const toStr   = `${months[dTo.getUTCMonth()]} ${String(dTo.getUTCDate()).padStart(2,'0')}, ${dTo.getUTCFullYear()}`;
    if (dFrom.getUTCFullYear() !== dTo.getUTCFullYear()) {
        return `${fromStr}, ${dFrom.getUTCFullYear()} – ${toStr}`;
    }
    return `${fromStr} – ${toStr}`;
}


// Update KPI Stats Card
function updateKPIs(data) {
    let totalImport = 0;
    let totalImportCost = 0;
    let totalExport = 0;
    let totalExportCredit = 0;
    let peakDemand = 0;
    
    // Sum consumption energy and cost
    if (data.consumption && data.consumption.length > 0) {
        data.consumption.forEach(point => {
            totalImport += point[1];
        });
        
        const res = resolutionSelect.value;
        let multiplier = 1;
        if (res === '15min') multiplier = 4;
        
        const peakKWh = Math.max(...data.consumption.map(point => point[1]), 0);
        peakDemand = peakKWh * multiplier;
    }
    if (data.consumption_cost && data.consumption_cost.length > 0) {
        data.consumption_cost.forEach(point => {
            totalImportCost += point[1];
        });
    }
    
    // Sum production energy and cost
    if (data.production && data.production.length > 0) {
        data.production.forEach(point => {
            totalExport += point[1];
        });
    }
    if (data.production_cost && data.production_cost.length > 0) {
        data.production_cost.forEach(point => {
            totalExportCredit += point[1];
        });
    }
    
    const netBalance = totalImport - totalExport;
    const netCost = totalImportCost - totalExportCredit;
    
    // Update UI Values
    kpiConsumptionVal.innerHTML = `${formatVal(totalImport)} <span class="kpi-unit">kWh</span>`;
    kpiConsumptionCost.innerText = `Cost: $${formatVal(totalImportCost)}`;
    
    kpiProductionVal.innerHTML = `${formatVal(totalExport)} <span class="kpi-unit">kWh</span>`;
    kpiProductionCost.innerText = totalExport > 0 ? `Credit: $${formatVal(totalExportCredit)}` : `Credit: $0.00 (No export)`;
    
    // If user hasn't explicitly customized export toggle, auto-disable export series when 0
    if (!userExplicitlyToggledExport) {
        chkShowExport.checked = totalExport > 0;
    }
    
    kpiNetVal.innerHTML = `${formatVal(netBalance)} <span class="kpi-unit">kWh</span>`;
    kpiNetCost.innerText = `Net Cost: $${formatVal(netCost)}`;
    
    kpiPeakVal.innerHTML = `${formatVal(peakDemand)} <span class="kpi-unit">kW</span>`;
    
    // Style net balance card depending on import vs export
    const netCard = document.querySelector('.card-net');
    if (netCard) {
        if (netBalance > 0) {
            netCard.style.borderColor = 'var(--color-consumption)';
            netCard.querySelector('.card-icon').style.color = 'var(--color-consumption)';
        } else {
            netCard.style.borderColor = 'var(--color-production)';
            netCard.querySelector('.card-icon').style.color = 'var(--color-production)';
        }
    }
}

// Update Time of Use Breakdown Card
function updateTOUBreakdown(data) {
    const touCard = document.getElementById('touCard');
    if (!touCard) return;
    
    // Update date badge on the Rate & Tier card
    const dateBadgeEl = document.getElementById('touCardDateBadge');
    const dateBadgeTextEl = document.getElementById('touCardDateText');
    const dateRangeStr = formatDateRange(data.date_from_ts, data.date_to_ts);
    if (dateBadgeEl && dateBadgeTextEl && dateRangeStr) {
        dateBadgeTextEl.textContent = dateRangeStr;
        dateBadgeEl.classList.remove('hidden');
    } else if (dateBadgeEl) {
        dateBadgeEl.classList.add('hidden');
    }
    
    const touSummary = data.tou_summary;
    const tierSummary = data.tier_summary;
    if (!touSummary && !tierSummary) {
        touCard.classList.add('hidden');
        return;
    }
    
    let showCard = false;
    
    // 1. Process TOU Section
    const touSection = document.getElementById('touStatsSection');
    if (touSummary && touSection) {
        const onPeakVal = touSummary.on_peak_kwh || 0;
        const midPeakVal = touSummary.mid_peak_kwh || 0;
        const offPeakVal = touSummary.off_peak_kwh || 0;
        const uloVal = touSummary.ulo_kwh || 0;
        const otherVal = touSummary.other_kwh || 0;
        const totalVal = onPeakVal + midPeakVal + offPeakVal + uloVal + otherVal;
        
        if (totalVal > 0) {
            touSection.classList.remove('hidden');
            showCard = true;
            
            const onPeakPct = ((onPeakVal / totalVal) * 100).toFixed(1);
            const midPeakPct = ((midPeakVal / totalVal) * 100).toFixed(1);
            const offPeakPct = ((offPeakVal / totalVal) * 100).toFixed(1);
            const uloPct = ((uloVal / totalVal) * 100).toFixed(1);
            const otherPct = ((otherVal / totalVal) * 100).toFixed(1);
            
            document.getElementById('touOnPeakVal').innerText = `${onPeakVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${onPeakPct}%)`;
            document.getElementById('touOnPeakCost').innerText = `$${(touSummary.on_peak_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('touOnPeakFill').style.width = `${onPeakPct}%`;
            
            document.getElementById('touMidPeakVal').innerText = `${midPeakVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${midPeakPct}%)`;
            document.getElementById('touMidPeakCost').innerText = `$${(touSummary.mid_peak_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('touMidPeakFill').style.width = `${midPeakPct}%`;
            
            document.getElementById('touOffPeakVal').innerText = `${offPeakVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${offPeakPct}%)`;
            document.getElementById('touOffPeakCost').innerText = `$${(touSummary.off_peak_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('touOffPeakFill').style.width = `${offPeakPct}%`;
            
            const uloGroup = document.getElementById('touUloGroup');
            if (uloGroup) {
                if (uloVal > 0) {
                    uloGroup.classList.remove('hidden');
                    document.getElementById('touUloVal').innerText = `${uloVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${uloPct}%)`;
                    document.getElementById('touUloCost').innerText = `$${(touSummary.ulo_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                    document.getElementById('touUloFill').style.width = `${uloPct}%`;
                } else {
                    uloGroup.classList.add('hidden');
                }
            }
            
            const otherGroup = document.getElementById('touOtherGroup');
            if (otherGroup) {
                if (otherVal > 0) {
                    otherGroup.classList.remove('hidden');
                    document.getElementById('touOtherVal').innerText = `${otherVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${otherPct}%)`;
                    document.getElementById('touOtherCost').innerText = `$${(touSummary.other_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                    document.getElementById('touOtherFill').style.width = `${otherPct}%`;
                } else {
                    otherGroup.classList.add('hidden');
                }
            }
            
            // Populate TOU Total row
            const totalCost = (touSummary.on_peak_cost || 0) + (touSummary.mid_peak_cost || 0) + (touSummary.off_peak_cost || 0) + (touSummary.ulo_cost || 0) + (touSummary.other_cost || 0);
            const touTotalValEl = document.getElementById('touTotalVal');
            const touTotalCostEl = document.getElementById('touTotalCost');
            if (touTotalValEl) touTotalValEl.innerText = `${totalVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh`;
            if (touTotalCostEl) touTotalCostEl.innerText = `$${totalCost.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        } else {
            touSection.classList.add('hidden');
        }
    } else if (touSection) {
        touSection.classList.add('hidden');
    }
    
    // 2. Process Tiered Section
    const tierSection = document.getElementById('tierStatsSection');
    if (tierSummary && tierSection) {
        const tier1Val = tierSummary.tier1_kwh || 0;
        const tier2Val = tierSummary.tier2_kwh || 0;
        const tier3Val = tierSummary.tier3_kwh || 0;
        const totalTierVal = tier1Val + tier2Val + tier3Val;
        
        if (totalTierVal > 0) {
            tierSection.classList.remove('hidden');
            showCard = true;
            
            const t1Pct = ((tier1Val / totalTierVal) * 100).toFixed(1);
            const t2Pct = ((tier2Val / totalTierVal) * 100).toFixed(1);
            const t3Pct = ((tier3Val / totalTierVal) * 100).toFixed(1);
            
            document.getElementById('tier1Val').innerText = `${tier1Val.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${t1Pct}%)`;
            document.getElementById('tier1Cost').innerText = `$${(tierSummary.tier1_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('tier1Fill').style.width = `${t1Pct}%`;
            
            document.getElementById('tier2Val').innerText = `${tier2Val.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${t2Pct}%)`;
            document.getElementById('tier2Cost').innerText = `$${(tierSummary.tier2_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('tier2Fill').style.width = `${t2Pct}%`;
            
            const t3Item = document.getElementById('tier3Val').closest('.tou-stat-item');
            if (t3Item) {
                if (tier3Val > 0) {
                    t3Item.classList.remove('hidden');
                    document.getElementById('tier3Val').innerText = `${tier3Val.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh (${t3Pct}%)`;
                    document.getElementById('tier3Cost').innerText = `$${(tierSummary.tier3_cost || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                    document.getElementById('tier3Fill').style.width = `${t3Pct}%`;
                } else {
                    t3Item.classList.add('hidden');
                }
            }
            
            // Populate Tier Total row
            const totalTierCost = (tierSummary.tier1_cost || 0) + (tierSummary.tier2_cost || 0) + (tierSummary.tier3_cost || 0);
            const tierTotalValEl = document.getElementById('tierTotalVal');
            const tierTotalCostEl = document.getElementById('tierTotalCost');
            if (tierTotalValEl) tierTotalValEl.innerText = `${totalTierVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh`;
            if (tierTotalCostEl) tierTotalCostEl.innerText = `$${totalTierCost.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        } else {
            tierSection.classList.add('hidden');
        }
    } else if (tierSection) {
        tierSection.classList.add('hidden');
    }
    
    // Adjust grid style depending on active sections
    const grid = touCard.querySelector('.breakdown-grid');
    if (grid) {
        const isTOUVisible = touSection && !touSection.classList.contains('hidden');
        const isTierVisible = tierSection && !tierSection.classList.contains('hidden');
        
        if (isTOUVisible && isTierVisible) {
            grid.style.gridTemplateColumns = ''; // default responsive layout
        } else {
            grid.style.gridTemplateColumns = '1fr'; // single-column if only one
        }
    }
    
    if (showCard) {
        touCard.classList.remove('hidden');
    } else {
        touCard.classList.add('hidden');
    }
}

// Update Estimated Alectra Bill Breakdown (Option C Layout)
function updateEstimatedBill(data) {
    const analyticsCard = document.getElementById('billingAnalyticsCard');
    if (!analyticsCard) return;

    const breakdown = data.bill_breakdown;
    if (!breakdown || (breakdown.total_amount_due === undefined && breakdown.total_amount_due === null)) {
        analyticsCard.classList.add('hidden');
        return;
    }

    analyticsCard.classList.remove('hidden');

    // Date Subtitle text — show actual data date range from API
    const dateSubEl = document.getElementById('billingDateSubtitle');
    const dateRangeStr = formatDateRange(data.date_from_ts, data.date_to_ts);
    if (dateSubEl) {
        if (dateRangeStr) {
            dateSubEl.innerText = `${dateRangeStr} • ${breakdown.days_count.toFixed(0)} Days`;
        } else {
            const rangePreset = dateRangeSelect ? dateRangeSelect.options[dateRangeSelect.selectedIndex].text : 'Selected Period';
            dateSubEl.innerText = `${rangePreset} • ${breakdown.days_count.toFixed(0)} Days Evaluated`;
        }
    }

    // Update active plan read-only badge from API response
    const planBadgeTextEl = document.getElementById('billActivePlanText');
    if (planBadgeTextEl && breakdown.active_rate_plan) {
        const planNames = {
            'tou': 'Standard TOU',
            'tiered': 'Tiered Pricing',
            'ulo': 'Ultra-Low Overnight'
        };
        planBadgeTextEl.textContent = planNames[breakdown.active_rate_plan] || breakdown.active_rate_plan;
    }

    // OER badge
    const oerBadge = document.getElementById('billOerBadge');
    if (oerBadge) {
        if (breakdown.apply_oer && breakdown.oer_percent > 0) {
            oerBadge.style.display = 'inline-flex';
            oerBadge.innerHTML = `<span class="badge-dot"></span> OER ${breakdown.oer_percent.toFixed(1)}% Applied`;
        } else {
            oerBadge.style.display = 'none';
        }
    }

    // Hero Due Amount & Subtitle
    const totalDueEl = document.getElementById('billTotalDue');
    if (totalDueEl) {
        totalDueEl.innerHTML = `$${breakdown.total_amount_due.toFixed(2)} <span class="currency">CAD</span>`;
    }

    const heroSubEl = document.getElementById('billHeroSub');
    if (heroSubEl) {
        const daysStr = breakdown.days_count.toFixed(0);
        heroSubEl.innerText = dateRangeStr
            ? `${dateRangeStr} • ${daysStr} Days`
            : `Estimated Total Due • ${daysStr} Days Evaluated`;
    }

    // Pre-Rebate and OER credit metrics
    const preRebateEl = document.getElementById('billPreRebateVal');
    if (preRebateEl) {
        preRebateEl.innerText = `$${breakdown.total_electricity_charges.toFixed(2)}`;
    }
    const oerCreditEl = document.getElementById('billOerCreditVal');
    if (oerCreditEl) {
        if (breakdown.apply_oer && breakdown.oer_rebate_amount > 0) {
            oerCreditEl.innerText = `-$${breakdown.oer_rebate_amount.toFixed(2)}`;
        } else {
            oerCreditEl.innerText = '$0.00';
        }
    }

    // Cost distribution bar segments
    const totalCharges = breakdown.total_electricity_charges || 1;
    const commPct = Math.max(5, (breakdown.commodity_cost / totalCharges) * 100);
    const delivPct = Math.max(5, (breakdown.total_delivery_cost / totalCharges) * 100);
    const regPct = Math.max(2, (breakdown.regulatory_cost / totalCharges) * 100);

    const barComm = document.getElementById('barCommodity');
    const barDeliv = document.getElementById('barDelivery');
    const barReg = document.getElementById('barRegulatory');
    if (barComm) barComm.style.width = `${commPct.toFixed(1)}%`;
    if (barDeliv) barDeliv.style.width = `${delivPct.toFixed(1)}%`;
    if (barReg) barReg.style.width = `${regPct.toFixed(1)}%`;

    // Itemized statement rows
    const commSub = document.getElementById('billCommoditySub');
    const commAmt = document.getElementById('billCommodityAmt');
    if (commSub) commSub.innerText = `Billed usage: ${breakdown.total_kwh.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} kWh`;
    if (commAmt) commAmt.innerText = `$${breakdown.commodity_cost.toFixed(2)}`;

    const delivSub = document.getElementById('billDeliverySub');
    const delivAmt = document.getElementById('billDeliveryAmt');
    if (delivSub) delivSub.innerText = `Fixed ($${breakdown.fixed_delivery_cost.toFixed(2)}/${breakdown.days_count}d) + Var (@ ${breakdown.line_loss_factor.toFixed(4)} loss)`;
    if (delivAmt) delivAmt.innerText = `$${breakdown.total_delivery_cost.toFixed(2)}`;

    const regSub = document.getElementById('billRegulatorySub');
    const regAmt = document.getElementById('billRegulatoryAmt');
    if (regSub) regSub.innerText = `IESO & RRRP ($${breakdown.regulatory_kwh.toFixed(6)}/kWh)`;
    if (regAmt) regAmt.innerText = `$${breakdown.regulatory_cost.toFixed(2)}`;

    const preTaxSub = document.getElementById('billPreTaxSubtotal');
    if (preTaxSub) preTaxSub.innerText = `$${breakdown.total_electricity_charges.toFixed(2)}`;

    const hstAmt = document.getElementById('billHstAmt');
    if (hstAmt) hstAmt.innerText = breakdown.apply_hst ? `+$${breakdown.hst_amount.toFixed(2)}` : '$0.00';

    const oerAmt = document.getElementById('billOerAmt');
    if (oerAmt) oerAmt.innerText = breakdown.apply_oer ? `-$${breakdown.oer_rebate_amount.toFixed(2)}` : '$0.00';

    const finalTotalAmt = document.getElementById('billFinalTotalAmt');
    if (finalTotalAmt) finalTotalAmt.innerText = `$${breakdown.total_amount_due.toFixed(2)} CAD`;
}

// Update Smart Rate Advisor (Option C Layout)
function updatePlanAdvisor(data) {
    const advisor = data.plan_advisor;
    if (!advisor) return;

    // Schedule Subtitle
    const schedSub = document.getElementById('advisorScheduleSubtitle');
    if (schedSub) {
        schedSub.innerText = `${advisor.season_name} Schedule`;
    }

    // Recommended Plan Banner
    const bestPlanEl = document.getElementById('advisorBestPlanName');
    if (bestPlanEl) bestPlanEl.innerText = advisor.recommended_plan;

    const savingsAmtEl = document.getElementById('advisorSavingsAmount');
    if (savingsAmtEl) {
        if (advisor.savings_vs_active > 0.05) {
            savingsAmtEl.innerText = `Est. Savings: $${advisor.savings_vs_active.toFixed(2)}`;
            savingsAmtEl.style.display = 'inline-block';
        } else {
            savingsAmtEl.innerText = `Matches Lowest`;
            savingsAmtEl.style.display = 'inline-block';
        }
    }

    // 3-Plan Comparison Table Rows
    const plansListEl = document.getElementById('advisorPlansList');
    if (plansListEl && advisor.plan_costs) {
        plansListEl.innerHTML = '';
        const minCost = Math.min(...advisor.plan_costs.map(p => p.cost));
        advisor.plan_costs.forEach(plan => {
            const isBest = plan.name === advisor.recommended_plan;
            const diff = plan.cost - minCost;
            const diffText = isBest ? 'Best' : `+$${diff.toFixed(2)}`;

            const row = document.createElement('div');
            row.className = `advisor-plan-row ${isBest ? 'is-best' : ''}`;
            row.innerHTML = `
                <div class="advisor-plan-name-cell">
                    ${isBest ? '<i data-lucide="check-circle" style="width:13px;height:13px;color:var(--color-production);flex-shrink:0;"></i>' : ''}
                    <span>${plan.name}</span>
                </div>
                <div class="advisor-plan-cost-cell">
                    $${plan.cost.toFixed(2)}
                </div>
                <div class="advisor-plan-diff-cell ${isBest ? 'is-best-diff' : ''}">
                    ${diffText}
                </div>
            `;
            plansListEl.appendChild(row);
        });
        if (window.lucide) {
            lucide.createIcons({ root: plansListEl });
        }
    }

    // AI Insight text
    const insightEl = document.getElementById('advisorInsightText');
    if (insightEl) {
        insightEl.innerText = advisor.insight_text;
    }
}

// Build or update ApexCharts
function renderChart(data) {
    if (!data) return;
    
    const hasData = (data.consumption && data.consumption.length > 0) || 
                    (data.production && data.production.length > 0);
                    
    const showImport = chkShowImport.checked;
    const showExport = chkShowExport.checked;
    
    if (!hasData || (!showImport && !showExport)) {
        chartEmpty.classList.remove('hidden');
        if (rateLegendBar) rateLegendBar.style.display = 'none';
        if (chart) {
            chart.destroy();
            chart = null;
        }
        return;
    }
    
    chartEmpty.classList.add('hidden');
    
    let series = [];
    let yAxisTitle = '';
    let tooltipFormat = '';
    
    const totalExport = (data.production || []).reduce((acc, curr) => acc + (curr[1] || 0), 0);
    
    const hasTOU = data.tou_summary && (
        (data.tou_summary.on_peak_kwh || 0) > 0 || 
        (data.tou_summary.mid_peak_kwh || 0) > 0 || 
        (data.tou_summary.off_peak_kwh || 0) > 0 || 
        (data.tou_summary.ulo_kwh || 0) > 0
    );
    
    const hasTier = data.tier_summary && (
        (data.tier_summary.tier1_kwh || 0) > 0 || 
        (data.tier_summary.tier2_kwh || 0) > 0 || 
        (data.tier_summary.tier3_kwh || 0) > 0
    );

    if (currentView === 'energy') {
        yAxisTitle = 'Energy (kWh)';
        tooltipFormat = ' kWh';
        chartSubtitle.innerText = 'Energy consumption color-coded by active billing rate periods';
    } else {
        yAxisTitle = 'Cost ($)';
        tooltipFormat = ' $';
        chartSubtitle.innerText = 'Monetary costs broken down by active billing rate periods';
    }
    
    // Always render rate-coded series when rate metadata is available
    if ((hasTOU || hasTier) && data.tou_breakdown) {
        if (rateLegendBar) rateLegendBar.style.display = 'flex';
        
        if (hasTOU) {
            // Show TOU Badges
            document.querySelectorAll('.rate-legend-bar .badge-onpeak, .rate-legend-bar .badge-midpeak, .rate-legend-bar .badge-offpeak').forEach(el => el.style.display = 'inline-flex');
            if (legendUlo) legendUlo.style.display = (data.tou_summary.ulo_kwh > 0) ? 'inline-flex' : 'none';
            if (legendTier1) legendTier1.style.display = 'none';
            if (legendTier2) legendTier2.style.display = 'none';
            
            if (showImport) {
                if (currentView === 'energy') {
                    series.push({
                        name: 'Off-Peak',
                        data: data.tou_breakdown.off_peak || [],
                        color: '#10b981'
                    });
                    if ((data.tou_summary.ulo_kwh || 0) > 0) {
                        series.push({
                            name: 'Ultra-Low Overnight',
                            data: data.tou_breakdown.ulo || [],
                            color: '#6366f1'
                        });
                    }
                    series.push({
                        name: 'Mid-Peak',
                        data: data.tou_breakdown.mid_peak || [],
                        color: '#f59e0b'
                    });
                    series.push({
                        name: 'On-Peak',
                        data: data.tou_breakdown.on_peak || [],
                        color: '#ef4444'
                    });
                } else {
                    series.push({
                        name: 'Off-Peak Cost',
                        data: data.tou_breakdown.off_peak_cost || [],
                        color: '#10b981'
                    });
                    if ((data.tou_summary.ulo_cost || 0) > 0) {
                        series.push({
                            name: 'ULO Cost',
                            data: data.tou_breakdown.ulo_cost || [],
                            color: '#6366f1'
                        });
                    }
                    series.push({
                        name: 'Mid-Peak Cost',
                        data: data.tou_breakdown.mid_peak_cost || [],
                        color: '#f59e0b'
                    });
                    series.push({
                        name: 'On-Peak Cost',
                        data: data.tou_breakdown.on_peak_cost || [],
                        color: '#ef4444'
                    });
                }
            }
        } else if (hasTier && data.tier_breakdown) {
            // Show Tier Badges
            document.querySelectorAll('.rate-legend-bar .badge-onpeak, .rate-legend-bar .badge-midpeak, .rate-legend-bar .badge-offpeak').forEach(el => el.style.display = 'none');
            if (legendUlo) legendUlo.style.display = 'none';
            if (legendTier1) legendTier1.style.display = 'inline-flex';
            if (legendTier2) legendTier2.style.display = (data.tier_summary.tier2_kwh > 0) ? 'inline-flex' : 'none';
            
            if (showImport) {
                if (currentView === 'energy') {
                    series.push({
                        name: 'Tier 1',
                        data: data.tier_breakdown.tier1 || [],
                        color: '#38bdf8'
                    });
                    if ((data.tier_summary.tier2_kwh || 0) > 0) {
                        series.push({
                            name: 'Tier 2',
                            data: data.tier_breakdown.tier2 || [],
                            color: '#f59e0b'
                        });
                    }
                    if ((data.tier_summary.tier3_kwh || 0) > 0) {
                        series.push({
                            name: 'Tier 3',
                            data: data.tier_breakdown.tier3 || [],
                            color: '#ef4444'
                        });
                    }
                } else {
                    series.push({
                        name: 'Tier 1 Cost',
                        data: data.tier_breakdown.tier1_cost || [],
                        color: '#38bdf8'
                    });
                    if ((data.tier_summary.tier2_cost || 0) > 0) {
                        series.push({
                            name: 'Tier 2 Cost',
                            data: data.tier_breakdown.tier2_cost || [],
                            color: '#f59e0b'
                        });
                    }
                    if ((data.tier_summary.tier3_cost || 0) > 0) {
                        series.push({
                            name: 'Tier 3 Cost',
                            data: data.tier_breakdown.tier3_cost || [],
                            color: '#ef4444'
                        });
                    }
                }
            }
        }
        
        if (showExport && totalExport > 0) {
            if (legendExport) legendExport.style.display = 'inline-flex';
            series.push({
                name: currentView === 'energy' ? 'Grid Export (Solar)' : 'Export Credit',
                data: currentView === 'energy' ? (data.production || []) : (data.production_cost || []),
                color: '#059669'
            });
        } else {
            if (legendExport) legendExport.style.display = 'none';
        }
    } else {
        // Fallback only if no rate metadata in dataset
        if (rateLegendBar) rateLegendBar.style.display = 'none';
        if (showImport) {
            series.push({
                name: currentView === 'energy' ? 'Grid Import (Consumption)' : 'Import Cost',
                data: currentView === 'energy' ? (data.consumption || []) : (data.consumption_cost || []),
                color: 'var(--color-consumption)'
            });
        }
        if (showExport && totalExport > 0) {
            series.push({
                name: currentView === 'energy' ? 'Grid Export (Production)' : 'Export Credit',
                data: currentView === 'energy' ? (data.production || []) : (data.production_cost || []),
                color: 'var(--color-production)'
            });
        }
    }
    
    const isStacked = (hasTOU || hasTier);
    const isBar = (currentChartType === 'bar');
    const curRes = (data && data.resolution) ? data.resolution : (resolutionSelect ? resolutionSelect.value : '1h');

    
    const options = {
        series: series,
        chart: {
            type: isBar ? 'bar' : 'area',
            stacked: isStacked,
            height: 420,
            background: 'transparent',
            foreColor: '#9ca3af',
            toolbar: {
                show: true,
                autoSelected: 'zoom',
                tools: {
                    download: true,
                    selection: true,
                    zoom: true,
                    zoomin: true,
                    zoomout: true,
                    pan: true,
                    reset: true
                }
            },
            zoom: {
                enabled: true,
                type: 'x',
                autoScaleYaxis: true
            },
            events: {
                zoomed: function(chartContext, { xaxis }) {
                    handleChartZoom(xaxis);
                },
                beforeResetZoom: function() {
                    if (isDrillDownActive) {
                        resetDrilldown();
                        return false;
                    }
                },
                dataPointSelection: function(event, chartContext, config) {
                    handleBarClick(config);
                }
            }
        },
        dataLabels: {
            enabled: false
        },
        stroke: isBar ? {
            show: false,
            width: 0
        } : {
            curve: 'smooth',
            width: 2
        },
        plotOptions: {
            bar: {
                horizontal: false,
                columnWidth: curRes === '1d' ? '65%' : (curRes === '15min' ? '92%' : '75%'),
                borderRadius: 2
            }
        },
        fill: isBar ? {
            opacity: 0.95
        } : {
            type: 'gradient',
            gradient: {
                opacityFrom: isStacked ? 0.6 : 0.4,
                opacityTo: 0.05,
            }
        },
        xaxis: {
            type: 'datetime',
            labels: {
                datetimeUTC: true,
                format: curRes === '1d' ? 'ddd, dd MMM' : (curRes === '1h' || curRes === '15min' ? 'ddd HH:mm' : 'MMM yyyy'),
                datetimeFormatter: {
                    year: 'yyyy',
                    month: "MMM 'yy",
                    day: 'ddd, dd MMM',
                    hour: 'ddd HH:mm'
                }
            }
        },
        yaxis: {
            title: {
                text: yAxisTitle
            },
            labels: {
                formatter: function (val) {
                    return currentView === 'cost' ? '$' + val.toFixed(2) : val.toFixed(2);
                }
            }
        },
        tooltip: {
            shared: true,
            intersect: false,
            theme: 'dark',
            custom: function({ series, seriesIndex, dataPointIndex, w }) {
                const xVal = (w.globals.seriesX && w.globals.seriesX[0]) ? w.globals.seriesX[0][dataPointIndex] : null;
                let headerDateStr = '';
                if (xVal) {
                    const d = new Date(xVal);
                    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
                    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                    const day = days[d.getUTCDay()];
                    const yr = d.getUTCFullYear();
                    const mo = months[d.getUTCMonth()];
                    const da = String(d.getUTCDate()).padStart(2, '0');
                    const hr = String(d.getUTCHours()).padStart(2, '0');
                    const mi = String(d.getUTCMinutes()).padStart(2, '0');
                    if (curRes === '1y') {
                        headerDateStr = `${yr}`;
                    } else if (curRes === '1m') {
                        headerDateStr = `${mo} ${yr}`;
                    } else if (curRes === '1d') {
                        headerDateStr = `${day}, ${da} ${mo} ${yr}`;
                    } else if (curRes === '1h') {
                        headerDateStr = `${day}, ${da} ${mo} ${yr} ${hr}:00`;
                    } else {
                        headerDateStr = `${day}, ${da} ${mo} ${yr} ${hr}:${mi}`;
                    }
                }

                let importTotal = 0;
                let exportTotal = 0;
                let itemsHtml = '';
                let activeSeriesCount = 0;

                for (let i = 0; i < series.length; i++) {
                    const val = series[i][dataPointIndex];
                    if (val !== undefined && val !== null) {
                        const name = w.globals.seriesNames[i] || '';
                        const color = w.globals.colors[i] || '#3b82f6';
                        const isExport = name.toLowerCase().includes('export');
                        
                        if (isExport) {
                            exportTotal += val;
                        } else {
                            importTotal += val;
                        }
                        
                        if (val > 0) {
                            activeSeriesCount++;
                        }

                        const formattedVal = currentView === 'cost' ? '$' + val.toFixed(4) : val.toFixed(3) + ' kWh';
                        itemsHtml += `
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 2px 0; gap: 14px;">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="width: 9px; height: 9px; border-radius: 50%; background-color: ${color}; display: inline-block;"></span>
                                    <span style="color: #cbd5e1; font-size: 12px;">${name}</span>
                                </div>
                                <span style="font-weight: 600; color: #f8fafc; font-size: 12px;">${formattedVal}</span>
                            </div>
                        `;
                    }
                }

                let totalHtml = '';
                // Always show total when multiple units/series are present
                if (series.length > 1 || activeSeriesCount > 1) {
                    const formattedImportTotal = currentView === 'cost' ? '$' + importTotal.toFixed(4) : importTotal.toFixed(3) + ' kWh';
                    if (exportTotal > 0) {
                        const netVal = importTotal - exportTotal;
                        const formattedNet = currentView === 'cost' ? '$' + netVal.toFixed(4) : netVal.toFixed(3) + ' kWh';
                        totalHtml = `
                            <div style="border-top: 1px solid rgba(255,255,255,0.15); margin-top: 6px; padding-top: 6px; display: flex; flex-direction: column; gap: 3px;">
                                <div style="display: flex; align-items: center; justify-content: space-between;">
                                    <span style="font-weight: 600; color: #94a3b8; font-size: 12px;">Total Import:</span>
                                    <span style="font-weight: 700; color: #f59e0b; font-size: 12px;">${formattedImportTotal}</span>
                                </div>
                                <div style="display: flex; align-items: center; justify-content: space-between;">
                                    <span style="font-weight: 700; color: #f8fafc; font-size: 12px;">Net:</span>
                                    <span style="font-weight: 700; color: #38bdf8; font-size: 13px;">${formattedNet}</span>
                                </div>
                            </div>
                        `;
                    } else {
                        totalHtml = `
                            <div style="border-top: 1px solid rgba(255,255,255,0.15); margin-top: 6px; padding-top: 6px; display: flex; align-items: center; justify-content: space-between; gap: 14px;">
                                <span style="font-weight: 700; color: #f8fafc; font-size: 12px;">Total:</span>
                                <span style="font-weight: 700; color: #38bdf8; font-size: 13px;">${formattedImportTotal}</span>
                            </div>
                        `;
                    }
                }

                return `
                    <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; box-shadow: 0 10px 25px rgba(0,0,0,0.6); font-family: Outfit, sans-serif; min-width: 170px;">
                        <div style="font-size: 12px; font-weight: 600; color: #94a3b8; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 4px;">
                            ${headerDateStr}
                        </div>
                        ${itemsHtml}
                        ${totalHtml}
                    </div>
                `;
            }
        },
        grid: {
            borderColor: 'var(--border-card)',
            strokeDashArray: 4,
            xaxis: {
                lines: {
                    show: true
                }
            }
        },
        legend: {
            position: 'top',
            horizontalAlign: 'right',
            show: !isStacked
        }
    };
    
    if (chart) {
        if (chart.w && chart.w.config && (
            chart.w.config.chart.type !== options.chart.type || 
            chart.w.config.chart.stacked !== options.chart.stacked ||
            isDrillDownActive
        )) {
            chart.destroy();
            chart = new ApexCharts(document.querySelector("#chart"), options);
            chart.render();
        } else {
            chart.updateOptions(options);
        }
    } else {
        chart = new ApexCharts(document.querySelector("#chart"), options);
        chart.render();
    }
}

// Drill-Down handlers & helpers
async function handleChartZoom(xaxis) {
    if (!xaxis || !xaxis.min || !xaxis.max) return;
    if (isDrillDownLoading) return;

    let startSec = Math.floor(xaxis.min / 1000);
    let endSec = Math.ceil(xaxis.max / 1000);
    const spanSec = endSec - startSec;
    if (spanSec <= 0) return;
    const spanDays = spanSec / 86400;

    const curRes = (globalData && globalData.resolution) ? globalData.resolution : (resolutionSelect ? resolutionSelect.value : '1d');

    // Zooming down to <= 2.2 days -> roll down to 15-minute resolution!
    if (spanDays <= 2.2) {
        if (curRes !== '15min' || !isDrillDownActive) {
            // Expand to full day(s) boundaries for clean 15-minute intervals
            const dMin = new Date(xaxis.min);
            const dMax = new Date(xaxis.max);
            const dayStartSec = Math.floor(Date.UTC(dMin.getUTCFullYear(), dMin.getUTCMonth(), dMin.getUTCDate(), 0, 0, 0) / 1000);
            let dayEndSec = Math.floor(Date.UTC(dMax.getUTCFullYear(), dMax.getUTCMonth(), dMax.getUTCDate(), 23, 59, 59) / 1000);
            if (dayEndSec <= dayStartSec) {
                dayEndSec = dayStartSec + 86399;
            }
            await fetchDrillDownData(dayStartSec, dayEndSec, '15min');
        }
    } else if (spanDays <= 14.5) {
        // Zooming down to <= 14 days -> roll down to hourly resolution!
        if (curRes !== '15min' && curRes !== '1h') {
            await fetchDrillDownData(startSec, endSec, '1h');
        }
    }
}

async function handleBarClick(config) {
    if (isDrillDownLoading) return;
    const curRes = (globalData && globalData.resolution) ? globalData.resolution : (resolutionSelect ? resolutionSelect.value : '1d');
    
    // Drill down on click if currently daily, monthly, or hourly
    if (curRes !== '1d' && curRes !== '1h' && curRes !== '1m') return;

    const seriesIndex = (config && config.seriesIndex >= 0) ? config.seriesIndex : 0;
    const dataPointIndex = config ? config.dataPointIndex : -1;
    if (dataPointIndex < 0) return;

    let xVal = null;
    if (config.w && config.w.globals && config.w.globals.seriesX && config.w.globals.seriesX[seriesIndex]) {
        xVal = config.w.globals.seriesX[seriesIndex][dataPointIndex];
    } else if (config.w && config.w.config && config.w.config.series && config.w.config.series[seriesIndex]) {
        const item = config.w.config.series[seriesIndex].data[dataPointIndex];
        xVal = Array.isArray(item) ? item[0] : (item && item.x ? item.x : null);
    }

    if (!xVal) return;

    const d = new Date(xVal);
    const dayStartSec = Math.floor(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 0, 0, 0) / 1000);
    const dayEndSec = dayStartSec + 86399;

    await fetchDrillDownData(dayStartSec, dayEndSec, '15min');
}

async function fetchDrillDownData(startSec, endSec, targetRes) {
    if (isDrillDownLoading) return;
    isDrillDownLoading = true;
    chartLoading.classList.remove('hidden');

    if (!isDrillDownActive) {
        preDrillDownState = {
            dateRange: dateRangeSelect.value,
            resolution: resolutionSelect.value,
            customStart: customStartInput.value,
            customEnd: customEndInput.value
        };
        isDrillDownActive = true;
    }

    try {
        const url = `/api/data?resolution=${targetRes}&start=${startSec}&end=${endSec}&_t=${Date.now()}`;
        const res = await fetch(url);
        const data = await res.json();
        globalData = data;

        const dStart = new Date(startSec * 1000);
        const dEnd = new Date(endSec * 1000);
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        const labelStart = `${days[dStart.getUTCDay()]}, ${dStart.getUTCDate()} ${months[dStart.getUTCMonth()]} ${dStart.getUTCFullYear()}`;
        const labelEnd = `${days[dEnd.getUTCDay()]}, ${dEnd.getUTCDate()} ${months[dEnd.getUTCMonth()]} ${dEnd.getUTCFullYear()}`;

        let dateLabel = labelStart;
        if (labelStart !== labelEnd && (endSec - startSec) > 86400) {
            dateLabel = `${labelStart} - ${labelEnd}`;
        }
        const resLabel = targetRes === '15min' ? '15-min' : (targetRes === '1h' ? 'Hourly' : targetRes);

        if (drilldownLabel) {
            drilldownLabel.textContent = `${dateLabel} (${resLabel})`;
        }
        if (drilldownBadge) {
            drilldownBadge.classList.remove('hidden');
        }

        renderChart(globalData);
        updateKPIs(globalData);
        updateTOUBreakdown(globalData);
        updateEstimatedBill(globalData);
        updatePlanAdvisor(globalData);
    } catch (err) {
        console.error("Error during drill-down:", err);
    } finally {
        chartLoading.classList.add('hidden');
        isDrillDownLoading = false;
    }
}

function resetDrilldown() {
    if (!isDrillDownActive) return;
    isDrillDownActive = false;
    if (drilldownBadge) {
        drilldownBadge.classList.add('hidden');
    }
    if (chart) {
        chart.destroy();
        chart = null;
    }

    if (preDrillDownState) {
        dateRangeSelect.value = preDrillDownState.dateRange;
        customStartInput.value = preDrillDownState.customStart;
        customEndInput.value = preDrillDownState.customEnd;
        syncResolutionOptions(preDrillDownState.resolution);
        resolutionSelect.value = preDrillDownState.resolution;
        preDrillDownState = null;
    }

    fetchDashboardData();
}


// Fetch dashboard data
async function fetchDashboardData() {
    chartLoading.classList.remove('hidden');
    
    const resolution = resolutionSelect.value;
    const dateRange = dateRangeSelect.value;
    
    // For all presets, delegate date resolution to the backend (anchored to latest DB data).
    // Only 'custom' computes start/end on the frontend.
    let url = `/api/data?resolution=${resolution}&_t=${Date.now()}`;

    if (dateRange === 'custom') {
        let start = null;
        let end = null;
        if (customStartInput.value) {
            const parts = customStartInput.value.split('-').map(Number);
            start = Math.floor(Date.UTC(parts[0], parts[1] - 1, parts[2]) / 1000);
        }
        if (customEndInput.value) {
            const parts = customEndInput.value.split('-').map(Number);
            end = Math.floor(Date.UTC(parts[0], parts[1] - 1, parts[2], 23, 59, 59) / 1000);
        }
        if (start) url += `&start=${start}`;
        if (end) url += `&end=${end}`;
    } else {
        // All presets: pass as date_range and let backend anchor to MAX(timestamp) in DB
        url += `&date_range=${dateRange}`;
    }
    
    try {
        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`Server returned HTTP ${res.status}: ${res.statusText}`);
        }
        globalData = await res.json();
        
        renderChart(globalData);
        updateKPIs(globalData);
        updateTOUBreakdown(globalData);
        updateEstimatedBill(globalData);
        updatePlanAdvisor(globalData);
    } catch (e) {
        console.error("Error fetching data:", e);
        showErrorToast(`Failed to load energy data: ${e.message || e}`, "Dashboard Data Error");
    } finally {
        chartLoading.classList.add('hidden');
    }
}

// Fetch status and history list
async function fetchStatus() {
    try {
        const res = await fetch(`/api/status?_t=${Date.now()}`);
        const status = await res.json();
        
        const pulse = syncStatusEl.querySelector('.pulse-dot');
        const text = syncStatusEl.querySelector('.status-text');
        
        if (status.last_error) {
            pulse.className = 'pulse-dot error';
            text.textContent = `Error: ${status.last_error}`;
        } else if (status.last_sync) {
            pulse.className = 'pulse-dot idle';
            const date = new Date(status.last_sync);
            text.textContent = `Last Sync: ${date.toLocaleTimeString()}`;
        } else {
            pulse.className = 'pulse-dot idle';
            text.textContent = 'Status: Ready';
        }
        
        scanIntervalMinutesInput.value = status.scan_interval_minutes;
        archiveRetentionDaysInput.value = status.archive_retention_days;
        timeShiftHoursInput.value = status.time_shift_hours;

        // Update Scraper Settings UI
        scraperRunTimeInput.value = status.scraper_run_time || '06:00';
        
        if (status.scraper_configured) {
            scraperConfigStatusEl.className = 'config-status';
            const lastRunStr = status.last_scraper_run ? new Date(status.last_scraper_run).toLocaleString() : 'Never';
            const lastErrStr = status.last_scraper_error ? `<br><span style="color:var(--color-danger)">Error: ${status.last_scraper_error}</span>` : '';
            scraperConfigStatusEl.innerHTML = `✓ Configured (Environment vars OK)<br>Last run: ${lastRunStr}${lastErrStr}`;
        } else {
            scraperConfigStatusEl.className = 'config-status missing';
            scraperConfigStatusEl.innerHTML = `✗ Missing Credentials<br>Set ACCOUNT_NAME, ACCOUNT_NUMBER, and PHONE_NUMBER in docker-compose.yml`;
        }

        // Smart Notification Check: Detect background scraper, sync, or system error
        const scraperErr = status.last_scraper_error;
        const generalErr = status.last_error;
        const isRealScraperErr = scraperErr && !scraperErr.startsWith("Running ");
        const effectiveErr = isRealScraperErr ? scraperErr : (generalErr || '');

        if (effectiveErr) {
            if (!userDismissedError || effectiveErr !== activeErrorMessage) {
                userDismissedError = false;
                const errTitle = isRealScraperErr ? "Alectra Scraper Error" : "Data / Sync Error";
                showErrorToast(effectiveErr, errTitle);
            }
        } else {
            if (!userDismissedError) {
                hideErrorToast();
                closeErrorModal();
            }
        }
        
        // Update manual scrape button status dynamically depending on scraper_active status
        if (status.scraper_active) {
            btnTriggerManualScrape.disabled = true;
            btnTriggerManualScrape.innerHTML = `<span class="spinner" style="width:12px; height:12px; border-width:2px; display:inline-block; margin-right:6px;"></span> Scraping...`;
        } else {
            btnTriggerManualScrape.disabled = false;
            btnTriggerManualScrape.innerHTML = `<i data-lucide="play"></i> Trigger Manual Scrape`;
            lucide.createIcons();
        }
        
        // Populate Import History List & Badge
        const fileCount = (status.recent_files && status.recent_files.length) ? status.recent_files.length : 0;
        if (historyCountBadge) {
            historyCountBadge.textContent = `${fileCount} ${fileCount === 1 ? 'file' : 'files'}`;
        }
        
        if (historyList) {
            if (fileCount > 0) {
                let listHTML = '';
                status.recent_files.forEach(file => {
                    const importedAtStr = formatLocalTime(file.processed_at * 1000);
                    const fileDateRangeStr = (file.start_time && file.end_time) ? 
                        `${formatDate(file.start_time * 1000)} – ${formatDate(file.end_time * 1000)}` : 
                        'Date N/A';
                    const intervalsCount = file.records_imported ? file.records_imported.toLocaleString() : '0';
                    
                    listHTML += `
                        <div class="history-item">
                            <div class="history-item-left">
                                <div class="history-item-icon">
                                    <i data-lucide="file-code"></i>
                                </div>
                                <div class="history-item-info">
                                    <span class="history-item-filename" title="${file.filename}">${file.filename}</span>
                                    <div class="history-item-meta">
                                        <span>Imported ${importedAtStr}</span>
                                        <span class="history-meta-dot">•</span>
                                        <span>${formatBytes(file.file_size)}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="history-item-chips">
                                <span class="history-chip chip-date" title="Coverage Period">
                                    <i data-lucide="calendar"></i> ${fileDateRangeStr}
                                </span>
                                <span class="history-chip chip-intervals" title="Processed Intervals">
                                    <i data-lucide="layers"></i> ${intervalsCount} pts
                                </span>
                            </div>
                        </div>
                    `;
                });
                historyList.innerHTML = listHTML;
                lucide.createIcons();
            } else {
                historyList.innerHTML = `
                    <div class="history-empty">
                        <i data-lucide="inbox"></i>
                        <p>No files processed yet</p>
                        <span>Imported XML files will appear here automatically.</span>
                    </div>
                `;
                lucide.createIcons();
            }
        }
        
        if (historyTableBody) {
            if (fileCount > 0) {
                let tableHTML = '';
                status.recent_files.forEach(file => {
                    const importedAtStr = formatLocalTime(file.processed_at * 1000);
                    const fileDateRangeStr = (file.start_time && file.end_time) ? 
                        `${formatDate(file.start_time * 1000)} to ${formatDate(file.end_time * 1000)}` : 
                        'N/A';
                    tableHTML += `
                        <tr>
                            <td><strong>${file.filename}</strong></td>
                            <td>${importedAtStr}</td>
                            <td>${formatBytes(file.file_size)}</td>
                            <td>${file.records_imported}</td>
                            <td>${fileDateRangeStr}</td>
                        </tr>
                    `;
                });
                historyTableBody.innerHTML = tableHTML;
            } else {
                historyTableBody.innerHTML = `<tr><td colspan="5" class="table-empty">No files processed yet.</td></tr>`;
            }
        }
    } catch (e) {
        console.error("Error fetching status:", e);
    }
}


// Chart Style (Bar vs Area) handlers
if (btnStyleBar && btnStyleArea) {
    btnStyleBar.addEventListener('click', () => {
        btnStyleBar.classList.add('active');
        btnStyleArea.classList.remove('active');
        currentChartType = 'bar';
        if (chart) { chart.destroy(); chart = null; }
        renderChart(globalData);
    });
    btnStyleArea.addEventListener('click', () => {
        btnStyleArea.classList.add('active');
        btnStyleBar.classList.remove('active');
        currentChartType = 'area';
        if (chart) { chart.destroy(); chart = null; }
        renderChart(globalData);
    });
}

// Toggle View handlers
btnViewEnergy.addEventListener('click', () => {
    btnViewEnergy.classList.add('active');
    btnViewCost.classList.remove('active');
    currentView = 'energy';
    renderChart(globalData);
});

// Cost View handler
btnViewCost.addEventListener('click', () => {
    btnViewCost.classList.add('active');
    btnViewEnergy.classList.remove('active');
    currentView = 'cost';
    renderChart(globalData);
});


// Checkbox Series Toggle handlers
chkShowImport.addEventListener('change', () => {
    renderChart(globalData);
});

chkShowExport.addEventListener('change', () => {
    userExplicitlyToggledExport = true;
    renderChart(globalData);
});

// Trigger Sync
btnSync.addEventListener('click', async () => {
    const pulse = syncStatusEl.querySelector('.pulse-dot');
    const text = syncStatusEl.querySelector('.status-text');
    
    pulse.className = 'pulse-dot syncing';
    text.textContent = 'Status: Syncing...';
    
    try {
        await fetch('/api/sync', { method: 'POST' });
        setTimeout(async () => {
            await fetchStatus();
            await fetchDashboardData();
        }, 1500);
    } catch (e) {
        console.error(e);
        pulse.className = 'pulse-dot error';
        text.textContent = 'Sync Trigger Failed';
    }
});

// Settings Modal & Tabs
btnSettings.addEventListener('click', () => {
    settingsModal.classList.remove('hidden');
    loadBillingParameters();
    loadOebRates();
});

// Settings Modal Tab Navigation
function initSettingsTabs() {
    const tabBtns = document.querySelectorAll('.tab-nav-btn');
    const tabPanes = document.querySelectorAll('.settings-tab-pane');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => {
                p.classList.remove('active');
                p.classList.add('hidden');
            });

            btn.classList.add('active');
            const targetPane = document.getElementById(targetId);
            if (targetPane) {
                targetPane.classList.remove('hidden');
                targetPane.classList.add('active');
            }
        });
    });
}

// Billing Parameters Loading & Saving
async function loadBillingParameters() {
    try {
        const res = await fetch('/api/billing/parameters');
        if (!res.ok) return;
        const p = await res.json();
        const fixEl = document.getElementById('billingFixedDelivery');
        const volEl = document.getElementById('billingVolumetricDelivery');
        const lineEl = document.getElementById('billingLineLoss');
        const regEl = document.getElementById('billingRegulatory');
        const oerEl = document.getElementById('billingOerPercent');
        const hstEl = document.getElementById('billingHstPercent');
        const applyHstEl = document.getElementById('billingApplyHst');
        const applyOerEl = document.getElementById('billingApplyOer');

        if (fixEl) fixEl.value = p.monthly_fixed_delivery;
        if (volEl) volEl.value = p.volumetric_delivery_kwh;
        if (lineEl) lineEl.value = p.line_loss_factor;
        if (regEl) regEl.value = p.regulatory_kwh;
        if (oerEl) oerEl.value = p.oer_percent;
        if (hstEl) hstEl.value = p.hst_percent;
        if (applyHstEl) applyHstEl.checked = p.apply_hst;
        if (applyOerEl) applyOerEl.checked = p.apply_oer;
    } catch (e) {
        console.error('Error loading billing parameters:', e);
    }
}

const billingForm = document.getElementById('billingForm');
const btnResetBillingParams = document.getElementById('btnResetBillingParams');

if (billingForm) {
    billingForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            monthly_fixed_delivery: parseFloat(document.getElementById('billingFixedDelivery').value),
            volumetric_delivery_kwh: parseFloat(document.getElementById('billingVolumetricDelivery').value),
            line_loss_factor: parseFloat(document.getElementById('billingLineLoss').value),
            regulatory_kwh: parseFloat(document.getElementById('billingRegulatory').value),
            oer_percent: parseFloat(document.getElementById('billingOerPercent').value),
            hst_percent: parseFloat(document.getElementById('billingHstPercent').value),
            apply_hst: document.getElementById('billingApplyHst').checked,
            apply_oer: document.getElementById('billingApplyOer').checked
        };

        try {
            const res = await fetch('/api/billing/parameters', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                alert("Alectra Statement Billing Parameters saved successfully!");
                settingsModal.classList.add('hidden');
                fetchDashboardData();
            } else {
                alert("Failed to save billing parameters.");
            }
        } catch (err) {
            console.error('Error saving billing parameters:', err);
            alert("Error saving billing parameters.");
        }
    });
}

if (btnResetBillingParams) {
    btnResetBillingParams.addEventListener('click', async () => {
        if (confirm("Reset Alectra billing parameters to official defaults ($35.38 fixed, $0.0175/kWh var, 1.0341 line loss, 23.5% OER, 13% HST)?")) {
            try {
                const res = await fetch('/api/billing/parameters/reset', { method: 'POST' });
                if (res.ok) {
                    await loadBillingParameters();
                    alert("Alectra billing parameters reset to official defaults!");
                    fetchDashboardData();
                }
            } catch (err) {
                console.error('Error resetting billing parameters:', err);
            }
        }
    });
}

// OEB Rates Loading & Saving
// UI displays rates in ¢/kWh; backend stores in $/kWh.
// Multiply by 100 on load ($/kWh → ¢), divide by 100 on save (¢ → $/kWh).
async function loadOebRates() {
    try {
        const res = await fetch('/api/billing/rates');
        if (!res.ok) return;
        const r = await res.json();

        const touOn = document.getElementById('rateTouOnPeak');
        const touMid = document.getElementById('rateTouMidPeak');
        const touOff = document.getElementById('rateTouOffPeak');
        const uloOver = document.getElementById('rateUloOvernight');
        const uloOff = document.getElementById('rateUloOffPeak');
        const uloMid = document.getElementById('rateUloMidPeak');
        const uloOn = document.getElementById('rateUloOnPeak');
        const tier1 = document.getElementById('rateTieredTier1');
        const tier2 = document.getElementById('rateTieredTier2');
        const sumSlab = document.getElementById('rateSummerThreshold');
        const winSlab = document.getElementById('rateWinterThreshold');

        // Convert $/kWh → ¢/kWh for display (round to 1 decimal)
        const toCents = v => parseFloat((v * 100).toFixed(1));
        if (touOn) touOn.value = toCents(r.tou_on_peak);
        if (touMid) touMid.value = toCents(r.tou_mid_peak);
        if (touOff) touOff.value = toCents(r.tou_off_peak);
        if (uloOver) uloOver.value = toCents(r.ulo_ultra_low_overnight);
        if (uloOff) uloOff.value = toCents(r.ulo_off_peak);
        if (uloMid) uloMid.value = toCents(r.ulo_mid_peak);
        if (uloOn) uloOn.value = toCents(r.ulo_on_peak);
        if (tier1) tier1.value = toCents(r.tiered_tier1);
        if (tier2) tier2.value = toCents(r.tiered_tier2);
        if (sumSlab) sumSlab.value = r.summer_slab_kwh;
        if (winSlab) winSlab.value = r.winter_slab_kwh;
    } catch (e) {
        console.error('Error loading OEB rates:', e);
    }
}

const ratesForm = document.getElementById('ratesForm');
const btnResetRates = document.getElementById('btnResetRates');

if (ratesForm) {
    ratesForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        // Convert ¢/kWh → $/kWh before sending to backend
        const toDollars = v => parseFloat((parseFloat(v) / 100).toFixed(6));
        const payload = {
            tou_on_peak: toDollars(document.getElementById('rateTouOnPeak').value),
            tou_mid_peak: toDollars(document.getElementById('rateTouMidPeak').value),
            tou_off_peak: toDollars(document.getElementById('rateTouOffPeak').value),
            ulo_ultra_low_overnight: toDollars(document.getElementById('rateUloOvernight').value),
            ulo_off_peak: toDollars(document.getElementById('rateUloOffPeak').value),
            ulo_mid_peak: toDollars(document.getElementById('rateUloMidPeak').value),
            ulo_on_peak: toDollars(document.getElementById('rateUloOnPeak').value),
            tiered_tier1: toDollars(document.getElementById('rateTieredTier1').value),
            tiered_tier2: toDollars(document.getElementById('rateTieredTier2').value),
            summer_slab_kwh: parseFloat(document.getElementById('rateSummerThreshold').value),
            winter_slab_kwh: parseFloat(document.getElementById('rateWinterThreshold').value)
        };

        try {
            const res = await fetch('/api/billing/rates', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                alert("OEB Rate Schedule saved successfully!");
                settingsModal.classList.add('hidden');
                fetchDashboardData();
            } else {
                alert("Failed to save rate schedule.");
            }
        } catch (err) {
            console.error('Error saving rate schedule:', err);
            alert("Error saving rate schedule.");
        }
    });
}

if (btnResetRates) {
    btnResetRates.addEventListener('click', async () => {
        if (confirm("Reset OEB rate schedule to official Ontario Energy Board defaults?")) {
            try {
                const res = await fetch('/api/billing/rates/reset', { method: 'POST' });
                if (res.ok) {
                    await loadOebRates();
                    alert("OEB rate schedule reset to official defaults!");
                    fetchDashboardData();
                }
            } catch (err) {
                console.error('Error resetting OEB rates:', err);
            }
        }
    });
}

btnCloseSettings.addEventListener('click', () => {
    settingsModal.classList.add('hidden');
});

settingsModal.addEventListener('click', (e) => {
    if (e.target === settingsModal) {
        settingsModal.classList.add('hidden');
    }
});

settingsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append('time_shift_hours', timeShiftHoursInput.value);
    formData.append('scan_interval_minutes', scanIntervalMinutesInput.value);
    formData.append('archive_retention_days', archiveRetentionDaysInput.value);
    formData.append('scraper_run_time', scraperRunTimeInput.value);
    
    try {
        await fetch('/api/settings', {
            method: 'POST',
            body: formData
        });
        alert("Settings saved successfully!");
        settingsModal.classList.add('hidden');
        fetchStatus();
        fetchDashboardData();
    } catch (err) {
        console.error(err);
        alert("Failed to save settings.");
    }
});

btnReimport.addEventListener('click', async () => {
    if (confirm("Are you sure you want to clear the database and re-import all XML files from the shared folder? This can take a few seconds.")) {
        const pulse = syncStatusEl.querySelector('.pulse-dot');
        const text = syncStatusEl.querySelector('.status-text');
        
        pulse.className = 'pulse-dot syncing';
        text.textContent = 'Status: Re-importing...';
        settingsModal.classList.add('hidden');
        
        try {
            await fetch('/api/reimport', { method: 'POST' });
            setTimeout(async () => {
                await fetchStatus();
                await fetchDashboardData();
                alert("Wipe and re-import completed!");
            }, 2000);
        } catch (e) {
            console.error(e);
            alert("Failed to trigger re-import.");
        }
    }
});

// Trigger Manual Scrape
btnTriggerManualScrape.addEventListener('click', async () => {
    const fromDate = scrapeFromDateInput.value;
    const toDate = scrapeToDateInput.value;
    
    if (!fromDate || !toDate) {
        alert("Please select both From Date and To Date.");
        return;
    }
    
    btnTriggerManualScrape.disabled = true;
    const origHTML = btnTriggerManualScrape.innerHTML;
    btnTriggerManualScrape.innerHTML = `<span class="spinner" style="width:12px; height:12px; border-width:2px; display:inline-block; margin-right:6px;"></span> Scraping...`;
    
    try {
        const res = await fetch('/api/scraper/scrape', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                from_date: fromDate,
                to_date: toDate
            })
        });
        const result = await res.json();
        
        if (result.status === 'success') {
            alert("Scraper run successfully triggered in the background. It may take 1-2 minutes to complete. We will poll the background progress and update the charts automatically.");
            settingsModal.classList.add('hidden');
            
            // Clean up any previously active polling timer
            if (activeScrapePollTimer) {
                clearInterval(activeScrapePollTimer);
                activeScrapePollTimer = null;
            }
            
            // Poll for status updates
            let pollAttempts = 0;
            activeScrapePollTimer = setInterval(async () => {
                pollAttempts++;
                await fetchStatus();
                
                // Fetch new data to see if loaded
                await fetchDashboardData();
                
                if (pollAttempts >= 8) { // stop polling after 2 minutes
                    clearInterval(activeScrapePollTimer);
                    activeScrapePollTimer = null;
                }
            }, 15000);
        } else {
            showErrorToast(result.message || "Failed to trigger scraper", "Scraper Error");
            alert(`Failed to trigger scraper: ${result.message}`);
        }
    } catch (err) {
        console.error("Scraper run request failed:", err);
        showErrorToast("Failed to trigger scraper: " + (err.message || err), "Network Error");
        alert("Failed to trigger scraper. Check console logs.");
    } finally {
        await fetchStatus();
    }
});

// Dynamic Resolution Auto-Switching and Option Constraint Matrix
function syncResolutionOptions(preferredRes = null) {
    const dateRange = dateRangeSelect.value;
    let daySpan = 30; // default for 30 days
    
    if (dateRange === 'latest_day') {
        daySpan = 1;
    } else if (dateRange === 'last_7_days') {
        daySpan = 7;
    } else if (dateRange === 'last_30_days') {
        daySpan = 30;
    } else if (dateRange === 'month_to_date') {
        daySpan = 31;
    } else if (dateRange === 'year_to_date' || dateRange === 'all_time') {
        daySpan = 365;
    } else if (dateRange === 'custom') {
        if (customStartInput.value && customEndInput.value) {
            const start = new Date(customStartInput.value);
            const end = new Date(customEndInput.value);
            daySpan = Math.max(1, Math.ceil((end - start) / (1000 * 60 * 60 * 24)));
        } else {
            daySpan = 30;
        }
    }
    
    const opt15min = resolutionSelect.querySelector('option[value="15min"]');
    const opt1h = resolutionSelect.querySelector('option[value="1h"]');
    const opt1d = resolutionSelect.querySelector('option[value="1d"]');
    const opt1m = resolutionSelect.querySelector('option[value="1m"]');
    const opt1y = resolutionSelect.querySelector('option[value="1y"]');
    
    if (daySpan <= 2) {
        // <= 2 days: 15-minute resolution available
        if (opt15min) { opt15min.disabled = false; opt15min.text = "15 Minutes"; }
        if (opt1h) { opt1h.disabled = false; opt1h.text = "Hourly"; }
        if (opt1d) { opt1d.disabled = false; opt1d.text = "Daily"; }
        if (opt1m) { opt1m.disabled = true; opt1m.text = "Monthly (Requires > 30 Days)"; }
        if (opt1y) { opt1y.disabled = true; opt1y.text = "Yearly (Requires > 365 Days)"; }
        
        if (!preferredRes) {
            resolutionSelect.value = '15min';
        }
    } else if (daySpan <= 14) {
        // 3 - 14 days: Hourly resolution available
        if (opt15min) { opt15min.disabled = true; opt15min.text = "15 Minutes (Max 1-2 Days)"; }
        if (opt1h) { opt1h.disabled = false; opt1h.text = "Hourly"; }
        if (opt1d) { opt1d.disabled = false; opt1d.text = "Daily"; }
        if (opt1m) { opt1m.disabled = true; opt1m.text = "Monthly (Requires > 30 Days)"; }
        if (opt1y) { opt1y.disabled = true; opt1y.text = "Yearly (Requires > 365 Days)"; }
        
        if (!preferredRes || resolutionSelect.value === '15min') {
            resolutionSelect.value = '1h';
        }
    } else {
        // > 14 days: Day-wise, Monthly, or Yearly
        if (opt15min) { opt15min.disabled = true; opt15min.text = "15 Minutes (Max 1-2 Days)"; }
        if (opt1h) { opt1h.disabled = true; opt1h.text = "Hourly (Max 14 Days)"; }
        if (opt1d) { opt1d.disabled = false; opt1d.text = "Daily"; }
        if (opt1m) { opt1m.disabled = false; opt1m.text = "Monthly"; }
        if (opt1y) { opt1y.disabled = false; opt1y.text = "Yearly"; }
        
        if (!preferredRes || resolutionSelect.value === '15min' || resolutionSelect.value === '1h') {
            resolutionSelect.value = '1d';
        }
    }
}

// Dropdown events
dateRangeSelect.addEventListener('change', () => {
    if (isDrillDownActive) {
        isDrillDownActive = false;
        preDrillDownState = null;
        if (drilldownBadge) drilldownBadge.classList.add('hidden');
    }
    if (dateRangeSelect.value === 'custom') {
        customDateGroup.classList.remove('hidden');
    } else {
        customDateGroup.classList.add('hidden');
    }
    syncResolutionOptions();
    fetchDashboardData();
});

resolutionSelect.addEventListener('change', () => {
    if (isDrillDownActive) {
        isDrillDownActive = false;
        preDrillDownState = null;
        if (drilldownBadge) drilldownBadge.classList.add('hidden');
    }
    fetchDashboardData();
});

if (btnResetDrilldown) {
    btnResetDrilldown.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        resetDrilldown();
    });
}

customStartInput.addEventListener('change', () => {
    syncResolutionOptions();
    fetchDashboardData();
});

customEndInput.addEventListener('change', () => {
    syncResolutionOptions();
    fetchDashboardData();
});

// Drag & Drop Uploads
dropzone.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', () => {
    uploadFiles(fileInput.files);
});

dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
});

dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dragover');
});

dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    uploadFiles(e.dataTransfer.files);
});

async function uploadFiles(files) {
    if (files.length === 0) return;
    
    const pulse = syncStatusEl.querySelector('.pulse-dot');
    const text = syncStatusEl.querySelector('.status-text');
    
    pulse.className = 'pulse-dot syncing';
    text.textContent = `Uploading ${files.length} file(s)...`;
    
    let successCount = 0;
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (!file.name.toLowerCase().endsWith('.xml')) {
            alert(`File ${file.name} is not an XML file and will be skipped.`);
            continue;
        }
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const res = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            const result = await res.json();
            if (result.status === 'success') {
                successCount++;
            } else {
                console.error(`Error uploading ${file.name}: ${result.message}`);
            }
        } catch (e) {
            console.error(`Error uploading ${file.name}:`, e);
        }
    }
    
    alert(`Successfully imported ${successCount} file(s).`);
    await fetchStatus();
    await fetchDashboardData();
}

// Initial Loading
window.addEventListener('load', () => {
    initSettingsTabs();
    syncResolutionOptions();
    fetchStatus();
    fetchDashboardData();

    // Auto-open calendar / time picker when clicking anywhere on date / time fields
    document.querySelectorAll('input[type="date"], input[type="time"]').forEach(input => {
        input.addEventListener('click', () => {
            if (typeof input.showPicker === 'function') {
                try { input.showPicker(); } catch (_) {}
            }
        });
    });
});
