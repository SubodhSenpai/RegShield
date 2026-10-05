import DocPage from '../components/doc-page';
import { docMetadata, loadDoc } from '../../lib/docs';
import { latestRelease } from '../../lib/release';

const doc = loadDoc('getting-started');

export const metadata = docMetadata(doc);

export default async function GettingStarted() {
  return <DocPage doc={loadDoc('getting-started', await latestRelease())} />;
}
