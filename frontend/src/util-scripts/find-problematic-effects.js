#!/usr/bin/env node
/**
 * Script to find potentially problematic useEffect patterns in React components
 *
 * Usage: node find-problematic-effects.js
 *
 * This script scans for common anti-patterns that can cause infinite re-renders:
 * - window.location in dependencies
 * - Callback functions in dependencies (fetch*, handle*, etc.)
 * - Context values without primitives extracted
 */

const fs = require('fs');
const path = require('path');

// Patterns to detect
const ANTI_PATTERNS = [
  {
    name: 'window.location in dependencies',
    pattern: /useEffect\([^)]+\],\s*\[[^\]]*window\.location[^\]]*\]/gs,
    severity: 'HIGH',
    suggestion: 'Use React Router\'s useLocation() hook instead'
  },
  {
    name: 'Callback function in dependencies',
    pattern: /useEffect\([^)]+\],\s*\[[^\]]*(?:fetch|handle|load|get|set)[A-Z]\w+[^\]]*\]/gs,
    severity: 'HIGH',
    suggestion: 'Remove callbacks from deps or use useCallback with empty deps'
  },
  {
    name: 'Translation function (t) in dependencies',
    pattern: /useEffect\([^)]+\],\s*\[[^\]]*\bt\b[^\]]*\]/gs,
    severity: 'MEDIUM',
    suggestion: 'Remove \'t\' from dependencies - translation updates shouldn\'t trigger effects'
  },
  {
    name: 'User object in dependencies',
    pattern: /useEffect\([^)]+\],\s*\[[^\]]*\buser\b[^\]]*\]/gs,
    severity: 'MEDIUM',
    suggestion: 'Extract primitive property like user?.id instead of entire user object'
  },
  {
    name: 'Props object in dependencies',
    pattern: /useEffect\([^)]+\],\s*\[[^\]]*\bprops\b[^\]]*\]/gs,
    severity: 'MEDIUM',
    suggestion: 'Destructure props and use individual values in dependencies'
  }
];

function findJsxFiles(dir, fileList = []) {
  const files = fs.readdirSync(dir);

  files.forEach(file => {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);

    if (stat.isDirectory()) {
      // Skip node_modules and build directories
      if (!['node_modules', 'build', 'dist', '.git'].includes(file)) {
        findJsxFiles(filePath, fileList);
      }
    } else if (file.match(/\.(jsx?|tsx?)$/)) {
      fileList.push(filePath);
    }
  });

  return fileList;
}

function analyzeFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  const issues = [];

  // Check for useEffect usage
  const hasUseEffect = content.includes('useEffect');
  if (!hasUseEffect) return issues;

  // Check each anti-pattern
  ANTI_PATTERNS.forEach(pattern => {
    const matches = content.match(pattern.pattern);
    if (matches) {
      matches.forEach(match => {
        // Extract line number
        const beforeMatch = content.substring(0, content.indexOf(match));
        const lineNumber = beforeMatch.split('\n').length;

        issues.push({
          file: filePath,
          line: lineNumber,
          severity: pattern.severity,
          pattern: pattern.name,
          suggestion: pattern.suggestion,
          code: match.substring(0, 100) + (match.length > 100 ? '...' : '')
        });
      });
    }
  });

  return issues;
}

function printResults(issues) {
  if (issues.length === 0) {
    console.log('✅ No problematic useEffect patterns found!');
    return;
  }

  console.log(`\n🔍 Found ${issues.length} potential issue(s):\n`);

  // Group by severity
  const high = issues.filter(i => i.severity === 'HIGH');
  const medium = issues.filter(i => i.severity === 'MEDIUM');
  const low = issues.filter(i => i.severity === 'LOW');

  const printIssues = (issueList, emoji) => {
    issueList.forEach((issue, index) => {
      const relativePath = issue.file.replace(process.cwd(), '.');
      console.log(`${emoji} [${issue.severity}] ${relativePath}:${issue.line}`);
      console.log(`   Pattern: ${issue.pattern}`);
      console.log(`   💡 ${issue.suggestion}`);
      console.log('');
    });
  };

  if (high.length > 0) {
    console.log(`\n🔴 HIGH PRIORITY (${high.length}):`);
    console.log('─'.repeat(80));
    printIssues(high, '🔴');
  }

  if (medium.length > 0) {
    console.log(`\n🟡 MEDIUM PRIORITY (${medium.length}):`);
    console.log('─'.repeat(80));
    printIssues(medium, '🟡');
  }

  if (low.length > 0) {
    console.log(`\n🟢 LOW PRIORITY (${low.length}):`);
    console.log('─'.repeat(80));
    printIssues(low, '🟢');
  }
}

function generateFixReport(issues) {
  if (issues.length === 0) return;

  const reportPath = path.join(process.cwd(), 'useEffect-issues-report.md');

  let report = '# useEffect Issues Report\n\n';
  report += `Generated: ${new Date().toISOString()}\n\n`;
  report += `Total issues found: ${issues.length}\n\n`;

  report += '## Summary by Severity\n\n';
  const severityCounts = {};
  issues.forEach(i => {
    severityCounts[i.severity] = (severityCounts[i.severity] || 0) + 1;
  });
  Object.entries(severityCounts).forEach(([severity, count]) => {
    report += `- ${severity}: ${count}\n`;
  });

  report += '\n## Issues by File\n\n';
  const byFile = {};
  issues.forEach(issue => {
    if (!byFile[issue.file]) byFile[issue.file] = [];
    byFile[issue.file].push(issue);
  });

  Object.entries(byFile).forEach(([file, fileIssues]) => {
    const relativePath = file.replace(process.cwd(), '.');
    report += `### ${relativePath}\n\n`;
    fileIssues.forEach(issue => {
      report += `**Line ${issue.line}** - [${issue.severity}] ${issue.pattern}\n\n`;
      report += `💡 **Fix:** ${issue.suggestion}\n\n`;
    });
  });

  fs.writeFileSync(reportPath, report);
  console.log(`\n📄 Detailed report saved to: ${reportPath}`);
}

// Main execution
console.log('🔍 Scanning for problematic useEffect patterns...\n');

const srcDir = path.join(process.cwd(), 'src');
if (!fs.existsSync(srcDir)) {
  console.error('❌ Error: src/ directory not found');
  console.error('   Make sure you run this from the frontend directory');
  process.exit(1);
}

const files = findJsxFiles(srcDir);
console.log(`📁 Scanning ${files.length} files...\n`);

const allIssues = [];
files.forEach(file => {
  const issues = analyzeFile(file);
  allIssues.push(...issues);
});

printResults(allIssues);
generateFixReport(allIssues);

// Exit with error code if high-severity issues found
const highSeverity = allIssues.filter(i => i.severity === 'HIGH');
if (highSeverity.length > 0) {
  console.log(`\n⚠️  ${highSeverity.length} high-priority issue(s) should be fixed to prevent infinite re-renders\n`);
  process.exit(1);
}
