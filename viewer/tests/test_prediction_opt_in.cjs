'use strict';
// Existing read-only viewer CI entrypoint. Its workflow is unchanged.
import('./test_navi.mjs').catch(error=>{console.error(error);process.exitCode=1;});
